"""
scoring.py — Batch LLM scoring module.

Two-model pipeline:
  • Gemma 4 31B IT       — fetch_description()  (parametric knowledge, no web)
  • Gemini 3.1 Flash Lite — batch_score()        (PDF inline, 10 jobs/call)

Key-fallback: every LLM call tries the primary client first; on 429 /
RESOURCE_EXHAUSTED it retries once with the backup client (GEMINI_API_KEY_2).
The backup key MUST be from a different Google project to have independent quota.
"""

import json
import re
import time
import requests
from dataclasses import dataclass

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_2,
    RESUME_FOLDER_ID, RESUME_LABELS,
    SCORING_MODEL, FETCH_DESCRIPTION_MODEL,
)


# ── Data type ─────────────────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    fit_score:      int          # 1–10
    best_resume:    str          # QT | QR | QA | Risk
    strengths:      str          # 2–3 concrete points, pipe-separated
    weaknesses:     str          # 1–2 honest gaps, pipe-separated
    low_confidence: bool = False # True when description was unavailable


# ── Client initialisation ──────────────────────────────────────────────────────

def init_clients() -> tuple[genai.Client, genai.Client | None]:
    """
    Return (primary_client, backup_client).
    backup_client is None if GEMINI_API_KEY_2 is not set or equals the primary key.
    """
    primary = genai.Client(api_key=GEMINI_API_KEY)
    backup  = (
        genai.Client(api_key=GEMINI_API_KEY_2)
        if GEMINI_API_KEY_2 and GEMINI_API_KEY_2 != GEMINI_API_KEY
        else None
    )
    return primary, backup


def init_client() -> genai.Client:
    """Backward-compatible single-client init."""
    return init_clients()[0]


# ── Model validation ───────────────────────────────────────────────────────────

def validate_models(
    client: genai.Client,
    backup_client: genai.Client | None = None,
) -> None:
    """
    Ping both models with a trivial prompt at pipeline startup.
    Catches bad API keys and deprecated model IDs before processing any jobs.
    Raises RuntimeError if every available key fails for a model.
    """
    print("Validating models…")
    test = types.Part.from_text(text="Reply with the single word OK.")
    cfg  = types.GenerateContentConfig(max_output_tokens=5)

    for i, (model, label, fatal) in enumerate([
        (SCORING_MODEL,           "Gemini (scoring)",      True),
        (FETCH_DESCRIPTION_MODEL, "Gemma  (descriptions)", False),  # non-fatal: jobs still scored with low_confidence
    ]):
        if i > 0:
            time.sleep(3)   # avoid hitting per-second rate limit between consecutive validation calls
        clients = [c for c in [client, backup_client] if c]
        ok = False
        for c in clients:
            try:
                r = c.models.generate_content(model=model, contents=test, config=cfg)
                if r.text:
                    tag = "(backup)" if c is not client else ""
                    print(f"  ✓ {label} {tag}".rstrip())
                    ok = True
                    break
            except Exception as exc:
                print(f"  ✗ {label}: {str(exc)[:120]}")
        if not ok:
            if fatal:
                raise RuntimeError(
                    f"Model validation failed for {label} ({model}). "
                    "Check GEMINI_API_KEY / GEMINI_API_KEY_2 and the model ID in config.py."
                )
            else:
                print(f"  ⚠ {label} unavailable — jobs will be scored on title/company only (low_confidence=True).")


# ── Resume loading ─────────────────────────────────────────────────────────────

def load_resumes(folder_id: str = RESUME_FOLDER_ID) -> dict[str, bytes]:
    """
    Download all 4 resume PDFs from the shared Google Drive folder.
    Returns {label: pdf_bytes} — raw bytes sent directly to Gemini as inline data.
    Matches files by label substring in filename (QT/QR/QA/Risk).
    """
    if not folder_id:
        raise SystemExit("RESUME_FOLDER_ID env var is not set.")

    print(f"Loading resumes from Drive folder {folder_id}…")
    file_map = _list_drive_folder(folder_id)

    if not file_map:
        raise SystemExit(
            "No PDF files found in the Drive folder. "
            "Ensure the folder is shared as 'Anyone with the link'."
        )

    print(f"  Found {len(file_map)} file(s): {', '.join(file_map.keys())}")
    resumes: dict[str, bytes] = {}

    for label in RESUME_LABELS:
        match = next(
            (fname for fname in file_map if label.lower() in fname.lower()), None
        )
        if not match:
            raise SystemExit(
                f"No file for resume '{label}' found in folder. "
                f"Filename must contain '{label}'."
            )
        file_id = file_map[match]
        print(f"  Downloading {label} ({match})…", end=" ", flush=True)
        pdf_bytes = _download_file(file_id)
        if pdf_bytes[:4] != b"%PDF":
            raise RuntimeError(f"File for label '{label}' is not a valid PDF.")
        print(f"{len(pdf_bytes):,} bytes ✓")
        resumes[label] = pdf_bytes

    return resumes


# ── Description pre-fetch ──────────────────────────────────────────────────────

def fetch_description(
    client: genai.Client,
    title: str,
    company: str,
    location: str,
    job_url: str = "",
    backup_client: genai.Client | None = None,
) -> str:
    """
    Generate a job description using Gemma 4 31B's parametric knowledge.
    On 429 / RESOURCE_EXHAUSTED, retries once with the backup client.
    Returns generated text, or empty string on failure / unknown company.
    """
    prompt = (
        f'Write a detailed job description for a "{title}" position at "{company}" '
        f'in "{location}".\n\n'
        f'Cover all of the following — write in full sentences and bullet points, '
        f'aiming for 400-600 words total:\n\n'
        f'1. Role Overview: what this person does day-to-day at {company} (2-3 sentences)\n'
        f'2. Key Responsibilities: 5-6 specific bullet points describing actual work\n'
        f'3. Required Qualifications: degree level, years of experience, hard requirements\n'
        f'4. Technical Skills: specific programming languages, tools, libraries, data sources '
        f'   that {company} actually uses for this role\n'
        f'5. Preferred / Nice-to-have: additional skills or experience that strengthen candidacy\n\n'
        f'Be specific to how {company} actually operates. '
        f'No company overview, no benefits section, no EEO boilerplate. '
        f'If you have no knowledge of this company or role type, say: UNKNOWN.'
    )
    sys = (
        "You are a quant finance recruiting expert with deep knowledge of "
        "quantitative finance firms and the roles they hire for. Generate "
        "accurate, detailed job descriptions based on what you know about "
        "each firm's quantitative work and hiring standards. "
        "Write comprehensive descriptions — do not truncate or summarise."
    )

    def _call(c: genai.Client) -> str:
        r = c.models.generate_content(
            model=FETCH_DESCRIPTION_MODEL,
            contents=types.Part.from_text(text=prompt),
            config=types.GenerateContentConfig(
                system_instruction=sys,
                max_output_tokens=1024,
            ),
        )
        text = (r.text or "").strip()
        if not text:
            print("      ⚠ Gemma returned empty response (safety filter / refusal)")
            return ""
        if "UNKNOWN" in text or len(text) < 100:
            print(f"      ⚠ Gemma: no knowledge of this role ({len(text)} chars)")
            return ""
        return text

    clients_to_try = [c for c in [client, backup_client] if c]

    for attempt, c in enumerate(clients_to_try):
        try:
            return _call(c)
        except Exception as exc:
            err = str(exc)
            is_rate_limit = "429" in err or "RESOURCE_EXHAUSTED" in err
            is_last = attempt == len(clients_to_try) - 1

            # Always try the backup key if primary fails for any reason
            if not is_last:
                reason = "429 rate limit" if is_rate_limit else type(exc).__name__
                print(f"      ↺ Gemma primary failed ({reason}) — switching to backup key…")
                continue

            # On last client: one more attempt after a wait if rate-limited
            if is_rate_limit:
                print("      ↺ 429 on all Gemma keys — waiting 10s then retrying…")
                time.sleep(10)
                try:
                    return _call(c)
                except Exception:
                    pass

            print(f"      ⚠ fetch_description failed ({type(exc).__name__}): {str(exc)[:120]}")
    return ""


# ── Batch scoring ──────────────────────────────────────────────────────────────

def batch_score(
    jobs: list[dict],
    resume_pdfs: dict[str, bytes],
    client: genai.Client,
    fetch_missing: bool = True,
    backup_client: genai.Client | None = None,
) -> list[ScoreResult | None]:
    """
    Score a batch of up to 10 jobs in a single LLM call.

    Args:
        jobs:          job dicts with keys: title, company, location, description
        resume_pdfs:   {label: pdf_bytes} from load_resumes()
        client:        primary genai.Client
        fetch_missing: if True, call fetch_description() for jobs with no description
        backup_client: fallback genai.Client on 429 (different project = independent quota)

    Returns list[ScoreResult | None] — None entries are retried individually.
    """
    if not jobs:
        return []

    # ── Pre-fetch missing descriptions ────────────────────────────────────────
    if fetch_missing:
        for i, job in enumerate(jobs):
            desc = str(job.get("description", "")).strip()
            if not desc or desc.lower() in ("nan", "none"):
                print(f"    [Job {i+1}] fetching description: {job.get('title','')[:40]} @ {job.get('company','')[:20]}")
                time.sleep(5)
                fetched = fetch_description(
                    client,
                    title         = str(job.get("title",    "")),
                    company       = str(job.get("company",  "")),
                    location      = str(job.get("location", "")),
                    job_url       = str(job.get("job_url",  "")),
                    backup_client = backup_client,
                )
                job["description"]    = fetched
                job["_was_no_desc"]   = True
                job["_fetched_chars"] = len(fetched)
                if fetched:
                    print(f"      → {len(fetched):,} chars")
                else:
                    print(f"      → not found, will score on title/company only")
    else:
        for job in jobs:
            desc = str(job.get("description", "")).strip()
            if not desc or desc.lower() in ("nan", "none"):
                job.setdefault("_was_no_desc",   True)
                job.setdefault("_fetched_chars", 0)

    # ── Build contents: PDF parts + jobs prompt ────────────────────────────────
    contents: list = []
    for label in RESUME_LABELS:
        contents.append(types.Part.from_text(text=f"=== RESUME: {label} ==="))
        contents.append(types.Part.from_bytes(
            data=resume_pdfs[label], mime_type="application/pdf"
        ))
    contents.append(types.Part.from_text(text=_build_jobs_prompt(jobs)))

    # ── Single LLM call with key fallback ─────────────────────────────────────
    results: list[ScoreResult | None] = [None] * len(jobs)
    clients_to_try = [c for c in [client, backup_client] if c]

    for attempt, c in enumerate(clients_to_try):
        try:
            response = c.models.generate_content(
                model=SCORING_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT),
            )
            results = _parse_batch_response(response.text, len(jobs))
            break
        except Exception as exc:
            err = str(exc)
            is_rate = "429" in err or "RESOURCE_EXHAUSTED" in err
            if is_rate and attempt == 0 and len(clients_to_try) > 1:
                print("    ↺ 429 on Gemini primary — switching to backup key…")
                continue
            print(f"    ⚠ Batch scoring error ({type(exc).__name__}): {str(exc)[:80]}")

    # ── Mark low_confidence for jobs that had no description ──────────────────
    for i, job in enumerate(jobs):
        if job.get("_was_no_desc") and results[i] is not None:
            if not job.get("_fetched_chars"):
                results[i].low_confidence = True

    # ── Retry individually for parse failures ──────────────────────────────────
    for i, result in enumerate(results):
        if result is None:
            print(f"    ↺ Retrying job {i+1} individually…")
            time.sleep(5)
            results[i] = score_single(jobs[i], resume_pdfs, client, backup_client)

    return results


# ── Single-job scoring (no recursion risk) ────────────────────────────────────

def score_single(
    job: dict,
    resume_pdfs: dict[str, bytes],
    client: genai.Client,
    backup_client: genai.Client | None = None,
) -> ScoreResult | None:
    """
    Score one job with a direct LLM call.
    Does NOT call batch_score — breaks the mutual-recursion risk.
    Used as the retry fallback inside batch_score and for the low-confidence
    re-score pass in the orchestrators.
    """
    contents: list = []
    for label in RESUME_LABELS:
        contents.append(types.Part.from_text(text=f"=== RESUME: {label} ==="))
        contents.append(types.Part.from_bytes(
            data=resume_pdfs[label], mime_type="application/pdf"
        ))
    contents.append(types.Part.from_text(text=_build_jobs_prompt([job])))

    clients_to_try = [c for c in [client, backup_client] if c]

    for attempt, c in enumerate(clients_to_try):
        try:
            response = c.models.generate_content(
                model=SCORING_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT),
            )
            parsed = _parse_batch_response(response.text, 1)
            if parsed[0] is not None:
                return parsed[0]
        except Exception as exc:
            err = str(exc)
            is_rate = "429" in err or "RESOURCE_EXHAUSTED" in err
            if is_rate and attempt == 0 and len(clients_to_try) > 1:
                continue
            print(f"    ⚠ score_single failed ({type(exc).__name__}): {str(exc)[:80]}")

    return None


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a career advisor evaluating job listings for a specific candidate.

CANDIDATE: Dhrubojeet Haldar
  • Financial Mathematics, NC State University (GPA 3.82, graduating Dec 2026)
  • CS background, IIT Roorkee
  • 2 years production experience at Wells Fargo: quantitative model validation
    on $48B consumer credit card portfolio (PSI, KS, ROC, SR 11-7 compliance,
    model governance reporting)
  • ES futures calendar spread mean-reversion strategy: Databento MBP-10
    nanosecond order book, OOS Sharpe +3.88, p=0.0265 (n=670)
  • G10 FX statistical arbitrage: Kalman filter dynamic hedge ratio, 14 pairs,
    OOS Sharpe 0.53 (6H) across 2016-2022 out-of-sample window
  • Skills: Python, C/C++, SAS, SQL, R; QuantLib, Vollib, Statsmodels;
    stochastic calculus, Monte Carlo, time series analysis, numerical optimisation
  • Bloomberg Terminal, Databento (MBP-10 order book data)

The candidate has four tailored resumes:
  QT   — Quantitative Trading  (vol surfaces, stochastic vol, ES microstructure,
          systematic FX/equities strategies, execution systems)
  QR   — Quantitative Research (signal design, stat arb, Kalman, production
          quant modelling at Wells Fargo, macro research)
  QA   — Quantitative Analytics (credit portfolio analytics, model performance
          diagnostics, regime-conditional drift, ROC/KS/PSI)
  Risk — Model Risk / Model Validation (SR 11-7, model governance, model
          validation, stochastic calculus, derivatives pricing, Monte Carlo)

EVALUATION RULES:
1. Read the job description and understand what it actually requires.
2. Compare all four resumes against those requirements.
3. Select the single best-matching resume.
4. List 2–3 SPECIFIC strengths — name actual skills, tools, or experiences
   that appear in BOTH the resume and the job description.
5. List 1–2 HONEST weaknesses — real gaps, missing tools, seniority concerns,
   or domain distance. Do not inflate. Do not list vague statements.
6. Assign a CALIBRATED fit score. A 7 means genuinely strong, not routine.

SCORING RUBRIC:
  9–10  Near-perfect: candidate's core skills map directly to job requirements
  7–8   Strong: most requirements met, at most one notable gap
  5–6   Decent: relevant direction but clear skill gaps or partial domain mismatch
  3–4   Weak: significant skill gaps or seniority level mismatch
  1–2   Poor: wrong track, unrelated domain, or role is clearly too senior

CAREER STAGE CONTEXT — READ CAREFULLY:
The candidate graduates December 2026 with ~2 years of professional experience (Wells Fargo).
He is targeting entry-level and early-career quant roles. Evaluate every role with this in mind.

EARLY-CAREER PROGRAM BOOST:
If the title or description contains explicit new-grad or early-career signals such as:
  "new analyst", "analyst program", "associate program", "new graduate", "entry level",
  "campus hire", "campus recruit", "rotational program", "0-2 years", "recent graduate",
  "class of 2025/2026/2027", "university hire", "early career"
→ This is the IDEAL fit for the candidate's career stage.
  Add +1 to the base fit score (capped at 10) and include in strengths:
  "Explicitly an early-career / new-grad program — ideal for Dec 2026 graduation"

EXPERIENCE CONCERN FLAG:
If the description explicitly requires 3+ years post-graduation or 5+ years total experience:
→ Add to weaknesses:
  "Role may require [X] years post-grad experience — verify seniority fit before applying"

UNLABELLED ROLES — DO NOT PENALISE:
Many top quant firms (Jane Street, Citadel, Two Sigma) post pure entry-level quant roles
with no level label — simply "Quantitative Researcher" or "Quantitative Trader". Do NOT
deduct points for missing senior experience when no seniority requirement is stated.
These firms routinely hire directly from PhD/MSc programmes into unlabelled positions.\
"""


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _trim_description(desc: str, max_chars: int = 4000) -> str:
    """Soft trim at paragraph boundary. Avoids cutting mid-sentence."""
    if not desc or len(desc) <= max_chars:
        return desc
    cutpoint = desc.rfind("\n\n", 0, max_chars)
    if cutpoint > max_chars * 0.7:
        return desc[:cutpoint].strip()
    return desc[:max_chars].strip()


def _build_jobs_prompt(jobs: list[dict]) -> str:
    jobs_block = ""
    for i, job in enumerate(jobs, 1):
        desc = str(job.get("description", "")).strip()
        if desc and desc.lower() not in ("nan", "none"):
            was_fetched  = job.get("_was_no_desc", False)
            source_note  = " [description generated via Gemma]" if was_fetched else ""
            desc_section = f"Description{source_note}:\n{_trim_description(desc)}"
            low_conf     = "true" if (was_fetched and not job.get("_fetched_chars")) else "false"
        else:
            desc_section = "(No description available — evaluate on title and company only)"
            low_conf     = "true"

        jobs_block += (
            f"\n--- Job {i} ---\n"
            f"Title:    {job.get('title', '')}\n"
            f"Company:  {job.get('company', '')}\n"
            f"Location: {job.get('location', '')}\n"
            f"{desc_section}\n"
            f"[low_confidence: {low_conf}]\n"
        )

    return f"""\
=== JOB LISTINGS — {len(jobs)} jobs to evaluate ===
{jobs_block}
=== OUTPUT INSTRUCTIONS ===
Evaluate each job ONE BY ONE against the four resumes above.
Respond ONLY with a valid JSON array of exactly {len(jobs)} objects — no markdown
fences, no text outside the array.

Schema for each object:
{{
  "job":            <integer, 1-based>,
  "best_resume":    "<QT|QR|QA|Risk>",
  "fit_score":      <integer 1–10>,
  "strengths":      "<2–3 concrete strengths, pipe-separated>",
  "weaknesses":     "<1–2 honest gaps or concerns, pipe-separated>",
  "low_confidence": <true|false>
}}

CRITICAL RULE FOR STRENGTHS:
Only list a strength if the specific skill, tool, project, or result appears
EXPLICITLY in the resume. Do not infer or generalise. If you cannot point to
an exact line in the resume that supports the claim, it is NOT a strength.

Examples of GOOD strengths (grounded in resume content):
  "ES futures calendar spread MBP-10 strategy directly matches HFT signal research requirement"
  "Kalman filter dynamic hedge ratio work (G10 FX, OOS Sharpe 0.53) aligns with systematic macro role"
  "Wells Fargo PSI/KS/ROC model validation experience matches model governance requirement"
  "QuantLib in skills section matches derivatives pricing tooling requirement"

Examples of BAD strengths (vague or inferred — do not write these):
  "Strong quantitative background" — too generic
  "Relevant experience in systematic strategies" — not tied to specific resume item
  "Proven track record in P&L attribution" — not explicitly in the resume
  "Good programming skills" — meaningless without naming the specific language and context
"""


# ── Response parsing ───────────────────────────────────────────────────────────

def _parse_batch_response(text: str, n_jobs: int) -> list[ScoreResult | None]:
    """Parse JSON array from LLM response. Robust to markdown fences."""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        return [None] * n_jobs

    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return [None] * n_jobs

    results: list[ScoreResult | None] = [None] * n_jobs
    for item in items:
        try:
            idx = int(item.get("job", 0)) - 1
            if not 0 <= idx < n_jobs:
                continue
            results[idx] = ScoreResult(
                fit_score      = max(1, min(10, int(item.get("fit_score", 5)))),
                best_resume    = str(item.get("best_resume", "QR")),
                strengths      = str(item.get("strengths",  "")).strip(),
                weaknesses     = str(item.get("weaknesses", "")).strip(),
                low_confidence = bool(item.get("low_confidence", False)),
            )
        except (KeyError, ValueError, TypeError):
            continue

    return results


# ── Google Drive helpers ───────────────────────────────────────────────────────

def _list_drive_folder(folder_id: str) -> dict[str, str]:
    """Fetch public Drive folder HTML → {filename: file_id}."""
    html  = requests.get(
        f"https://drive.google.com/drive/folders/{folder_id}", timeout=30
    ).text
    ids   = [i for i in dict.fromkeys(re.findall(r'\b(1[A-Za-z0-9_-]{32})\b', html))
             if i != folder_id]
    names = list(dict.fromkeys(re.findall(r'"([^"]+\.pdf)"', html, re.IGNORECASE)))
    return dict(zip(names, ids))


def _download_file(file_id: str) -> bytes:
    """Download Google Drive file, handling virus-scan confirmation pages."""
    session  = requests.Session()
    base_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp     = session.get(base_url, stream=True, timeout=30)
    token    = next(
        (v for k, v in resp.cookies.items() if k.startswith("download_warning")), None
    )
    if token:
        resp = session.get(base_url, params={"confirm": token}, stream=True, timeout=60)
    resp.raise_for_status()
    return resp.content
