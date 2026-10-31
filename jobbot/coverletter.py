"""Generate a truthful, job-specific cover letter from the candidate profile and job description."""
from . import ai
from .tailor import compact_jd, _j


def write(profile, jd, title="", company=""):
    prompt = f"""Write a concise, specific cover letter for this job application (250-350 words).
Use only verifiable facts in the candidate profile. Do not invent experience, achievements, tools,
metrics, or reasons for interest. Connect the strongest relevant evidence to the job requirements.
Use a professional, natural tone, no placeholders, no generic claims, and do not include a postal
address or date. Return only the letter body, with a short greeting and sign-off.

JOB: {title} at {company}
JOB DESCRIPTION:
{compact_jd(jd)}

CANDIDATE PROFILE (only source of truth):
{_j(profile)}"""
    return ai.ask(prompt).strip()
