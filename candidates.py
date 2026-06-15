"""
candidates.py — Multi-candidate configuration for resume scoring.

Each candidate has their own Google Drive folder, system prompt, and Notion
column names. Only candidates with a configured resume folder ID are active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from config import (
    RESUME_FOLDER_ID,
    RESUME_FOLDER_ID_DHRUBO,
    RESUME_FOLDER_ID_SHREYANSH,
    RESUME_LABELS,
)
from scoring import ScoreResult, batch_score, load_resumes, score_single


# ── Shared rubric (appended to every candidate-specific bio) ───────────────────

_EVALUATION_RULES = """\
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

EARLY-CAREER PROGRAM BOOST:
If the title or description contains explicit new-grad or early-career signals such as:
  "new analyst", "analyst program", "associate program", "new graduate", "entry level",
  "campus hire", "campus recruit", "rotational program", "0-2 years", "recent graduate",
  "class of 2025/2026/2027", "university hire", "early career"
→ This is the IDEAL fit for an entry-level quant candidate.
  Add +1 to the base fit score (capped at 10) and include in strengths:
  "Explicitly an early-career / new-grad program — ideal for target graduation stage"

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


# ── Candidate profiles ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    id: str
    display_name: str
    resume_folder_env: str
    resume_labels: tuple[str, ...]
    fit_score_col: str
    best_resume_col: str
    ai_notes_col: str
    system_prompt: str

    def resume_folder_id(self) -> str:
        if self.id == "dhrubo":
            return RESUME_FOLDER_ID_DHRUBO or RESUME_FOLDER_ID
        if self.id == "shreyansh":
            return RESUME_FOLDER_ID_SHREYANSH
        return os.environ.get(self.resume_folder_env, "").strip()


DHRUBO_PROMPT = f"""\
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

CAREER STAGE CONTEXT — READ CAREFULLY:
The candidate graduates December 2026 with ~2 years of professional experience (Wells Fargo).
He is targeting entry-level and early-career quant roles. Evaluate every role with this in mind.

{_EVALUATION_RULES}\
"""

# Parsed from Drive folder 1C2ux-G4RQCISciPmvaeRltsd3rvvMy7V (Software, Trading, ML, Derivatives).
SHREYANSH_RESUME_LABELS = ("Software", "Trading", "ML", "Derivatives")

SHREYANSH_PROMPT = f"""\
You are a career advisor evaluating job listings for a specific candidate.

CANDIDATE: Shreyansh Kumar Sharma
  • Master of Financial Mathematics, NC State University (GPA 3.96, graduating Dec 2026)
  • B.S. Mathematics and Computing, IIT Kharagpur (GPA 3.37, Aug 2021–Jul 2025);
    Micro Specialization in Entrepreneurship and Innovation
  • Franklin Templeton Investments — Gen AI Product Engineering Intern & Co-op
    (May 2024–Mar 2025): SQL-GPT chatbot (Django, OpenAI, React), Azure Postgres
    query executor with territory-based access control, NLP/transformer pipeline
    scoring 1,000+ sales notes for follow-up prediction, macro-signal synthesis
    for client talking points
  • Local volatility pricing framework on 5,000+ SPX contracts: SVI calibration
    (2.47% IV RMSE, no-butterfly constraints), Dupire surface with isotonic
    splines, Crank-Nicolson PDE engine (delta err <0.02, vega MAE <1)
  • Lifted Volterra-Heston model: rough-Heston calibration to SPX vol surface,
    kernel approximation to finite-dimensional Markov system, Monte Carlo +
    Longstaff-Schwartz for American option early exercise
  • Explainable autoencoder factor models for commodities (Morgan Stanley mentorship):
    22 return series → 5 latent factors; forecast-based and temporal Shapley
    decomposition for out-of-sample accuracy and regime shifts
  • Pairs trading (AAPL/MSFT): Engle-Granger cointegration (p=0.042), half-life
    8.2d, OOS Sharpe 1.5 / Sortino 3.1 (2024–2025); momentum L/S on S&P 500:
    25% annual return, Sharpe 1.95, CAPM alpha 10.7%, beta 0.51
  • Skills: Python, C++, SQL, R; NumPy, Pandas, SciPy, Scikit-learn, QuantLib,
    PySpark; stochastic calculus, Monte Carlo, numerical methods, regression;
    Bloomberg Terminal, QuantConnect, Databricks, Git/Docker

The candidate has four tailored resumes:
  Software   — Full-stack & AI engineering in finance (Django, React, Streamlit,
               LangChain, RAG/ChromaDB, SQL-GPT, OpenAI SDK, Docker, PostgreSQL;
               ncBacktester OOP backtesting package on PyPI; KOSS leadership)
  Trading    — Systematic trading & execution (pairs trading, cross-sectional
               momentum L/S, Almgren-Chriss transaction-cost model on QuantConnect,
               XGBoost/LogReg signal pipelines, ncBacktester, stress-testing
               under transaction costs)
  ML         — Machine learning & data-driven quant (nonlinear autoencoder factor
               models, Shapley interpretability, XGBoost from scratch, technical-
               indicator ML signals, Franklin Templeton NLP/transformer pipelines)
  Derivatives — Derivatives pricing & volatility (local vol/SVI/Dupire/PDE Greeks,
               Volterra-Heston American options, Bermudan swaption pricer in progress,
               commodity factor models, QuantLib, fixed-income & options coursework)

CAREER STAGE CONTEXT — READ CAREFULLY:
The candidate graduates December 2026 with one year of industry experience (Franklin
Templeton) plus substantial independent and course quant projects. He is targeting
entry-level and early-career quant roles. Evaluate every role with this in mind.

{_EVALUATION_RULES}\
"""


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        id="dhrubo",
        display_name="Dhrubo",
        resume_folder_env="RESUME_FOLDER_ID_DHRUBO",
        resume_labels=RESUME_LABELS,
        fit_score_col="Fit Score-Dhrubo",
        best_resume_col="Best Resume-Dhrubo",
        ai_notes_col="AI Notes-Dhrubo",
        system_prompt=DHRUBO_PROMPT,
    ),
    Candidate(
        id="shreyansh",
        display_name="Shreyansh",
        resume_folder_env="RESUME_FOLDER_ID_SHREYANSH",
        resume_labels=SHREYANSH_RESUME_LABELS,
        fit_score_col="Fit Score-Shreyansh",
        best_resume_col="Best Resume-Shreyansh",
        ai_notes_col="AI Notes-Shreyansh",
        system_prompt=SHREYANSH_PROMPT,
    ),
)


def get_configured_candidates() -> list[Candidate]:
    """Return candidates that have a resume folder ID set."""
    return [c for c in CANDIDATES if c.resume_folder_id()]


def candidate_by_id(candidate_id: str) -> Candidate:
    for candidate in CANDIDATES:
        if candidate.id == candidate_id:
            return candidate
    raise KeyError(f"Unknown candidate id: {candidate_id}")


# ── Resume + scoring helpers ───────────────────────────────────────────────────

def load_all_resumes(candidates: list[Candidate] | None = None) -> dict[str, dict[str, bytes]]:
    """Load resume PDFs for each configured candidate. Returns {id: {label: bytes}}."""
    active = candidates or get_configured_candidates()
    if not active:
        raise SystemExit(
            "No resume folders configured. Set RESUME_FOLDER_ID_DHRUBO and/or "
            "RESUME_FOLDER_ID_SHREYANSH (legacy: RESUME_FOLDER_ID for Dhrubo)."
        )

    resumes: dict[str, dict[str, bytes]] = {}
    for candidate in active:
        print(f"\n── {candidate.display_name} ({candidate.id}) ──")
        resumes[candidate.id] = load_resumes(
            candidate.resume_folder_id(),
            labels=candidate.resume_labels,
        )
    return resumes


def score_batch_all(
    jobs: list[dict],
    resumes_by_candidate: dict[str, dict[str, bytes]],
    client,
    *,
    fetch_missing: bool = True,
    backup_client=None,
    candidates: list[Candidate] | None = None,
) -> dict[str, list[ScoreResult | None]]:
    """
    Score a job batch for every active candidate.
    Description fetching runs once (on the shared job dicts).
    """
    active = candidates or [
        candidate_by_id(cid) for cid in resumes_by_candidate
    ]
    results: dict[str, list[ScoreResult | None]] = {}

    for i, candidate in enumerate(active):
        if i == 0:
            results[candidate.id] = batch_score(
                jobs,
                resumes_by_candidate[candidate.id],
                client,
                fetch_missing=fetch_missing,
                backup_client=backup_client,
                system_prompt=candidate.system_prompt,
                resume_labels=candidate.resume_labels,
            )
        else:
            results[candidate.id] = batch_score(
                jobs,
                resumes_by_candidate[candidate.id],
                client,
                fetch_missing=False,
                backup_client=backup_client,
                system_prompt=candidate.system_prompt,
                resume_labels=candidate.resume_labels,
            )

    return results


def score_single_all(
    job: dict,
    resumes_by_candidate: dict[str, dict[str, bytes]],
    client,
    backup_client=None,
    candidates: list[Candidate] | None = None,
) -> dict[str, ScoreResult | None]:
    """Score one job for every active candidate."""
    active = candidates or [
        candidate_by_id(cid) for cid in resumes_by_candidate
    ]
    return {
        candidate.id: score_single(
            job,
            resumes_by_candidate[candidate.id],
            client,
            backup_client=backup_client,
            system_prompt=candidate.system_prompt,
            resume_labels=candidate.resume_labels,
        )
        for candidate in active
    }


def any_low_confidence(
    scores: dict[str, ScoreResult | None],
    job: dict,
) -> bool:
    """True if any candidate was scored without a usable description."""
    if not job.get("_was_no_desc") or job.get("_fetched_chars"):
        return False
    return any(score and score.low_confidence for score in scores.values())
