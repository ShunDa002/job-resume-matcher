from .models import CandidateProfile,JobRecord,EligibilityStatus

def determine_eligibility(candidate:CandidateProfile,job:JobRecord,policy:dict):
    reasons=[]; risk="none"
    if job.required_citizenship_country_code and job.required_citizenship_country_code != candidate.citizenship_country_code:
        return EligibilityStatus.INELIGIBLE_CITIZENSHIP,[f"Requires citizenship {job.required_citizenship_country_code}; candidate citizenship is {candidate.citizenship_country_code}."],"not_applicable"
    threshold=policy["fresh_graduate"]["reject_required_experience_years_at_or_above"]
    cond=policy["fresh_graduate"]["conditional_required_experience_years_at_or_above"]
    if job.experience_requirement_type=="required" and job.minimum_experience_years is not None:
        if candidate.career_level=="fresh_graduate" and job.minimum_experience_years>=threshold:
            return EligibilityStatus.INELIGIBLE_EXPERIENCE,[f"Requires {job.minimum_experience_years:g}+ years; candidate has {candidate.professional_experience_years:g} years."],"not_applicable"
    if job.career_level in set(policy["excluded_seniority_levels"]) and candidate.career_level=="fresh_graduate":
        return EligibilityStatus.INELIGIBLE_SENIORITY,[f"Career level '{job.career_level}' is excluded for a fresh graduate."],"not_applicable"
    # Enrollment check: a job that requires current enrollment (the
    # usual internship condition) cannot be taken by a candidate who
    # is not currently enrolled. This is what filters internships.
    if policy.get("enrollment",{}).get("requires_current_enrollment_is_ineligible") and job.requires_current_enrollment and not candidate.currently_enrolled:
        return EligibilityStatus.INELIGIBLE_ENROLLMENT,["Requires current enrollment; candidate is not currently enrolled."],"not_applicable"
    if job.location_country_code != candidate.citizenship_country_code and not candidate.has_target_country_work_rights:
        if job.sponsorship=="not_available":
            return EligibilityStatus.INELIGIBLE_WORK_AUTHORIZATION,["Candidate lacks target-country work rights and sponsorship is unavailable."],"high"
        if job.sponsorship=="unknown": reasons.append("Work authorization sponsorship is not stated."); risk="unknown"
    if job.experience_requirement_type=="required" and job.minimum_experience_years is not None and job.minimum_experience_years>=cond and candidate.professional_experience_years<job.minimum_experience_years:
        reasons.append(f"Candidate has less than the required {job.minimum_experience_years:g} years.")
    # A "preferred" experience minimum is not a hard gate, but the gap
    # must still be visible: a high skill score must not hide that the
    # employer prefers far more experience than the candidate has.
    if job.experience_requirement_type=="preferred" and job.minimum_experience_years is not None and job.minimum_experience_years>=cond and candidate.professional_experience_years<job.minimum_experience_years:
        reasons.append(f"Prefers {job.minimum_experience_years:g}+ years; candidate has {candidate.professional_experience_years:g} years.")
    if candidate.target_employment_types and job.employment_type not in candidate.target_employment_types:
        reasons.append(f"Employment type '{job.employment_type}' is outside candidate targets.")
    # Nothing extractable at all: no requirements, no degree, no
    # experience minimum. There is nothing to score, so this is not a
    # match of any kind -- not even a conditional one. A score averaged
    # over zero requirements would be a vacuous 100.
    if not job.requirements and not job.degree_fields and job.minimum_experience_years is None:
        return EligibilityStatus.INSUFFICIENT_INFORMATION,["No requirements, degree, or experience minimum could be extracted from the job description; there is nothing to score."],"not_applicable"
    return (EligibilityStatus.CONDITIONALLY_ELIGIBLE if reasons else EligibilityStatus.ELIGIBLE),reasons,risk
