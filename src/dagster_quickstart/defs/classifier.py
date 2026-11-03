import html
import re

COMPANY_SUBJECT_PATTERNS = [
    r"applying to .*\bat ([A-Z][\w&.,' -]+?)(?:\s*[-|!]|\s*$)",      # "applying to <role> at X"
    r"application\b.*\bat ([A-Z][\w&.,' -]+?)(?:\s*[-|!]|\s*$)",      # "application at X", "application – <role> at X"
    r"applying to ([A-Z][\w&.,' -]+?)(?:\s*[-|!]|\s*$)",              # "applying to X" (no "at")
    r"application to ([A-Z][\w&.,' -]+?)(?:\s*[-|!]|\s*$)",           # "application to X"
    r"application with ([A-Z][\w&.,' -]+?)(?:\s*[-|!]|\s*$)",         # "application with X"
    r"^([A-Z][\w&.,' -]+?)\s*[|]",                                    # "Motive | Following up..."
]

DISPLAY_NAME_NOISE_WORDS = {
    "talent", "team", "hiring", "recruiting", "recruitment", "careers",
    "hr", "people", "acquisition", "acquisitions", "notifications",
    "no-reply", "noreply",
}

KNOWN_NON_COMPANY_NAMES = {"annabelle mazagwu", "annabelle", "mazagwu", "gmail", "greenhouse", "team"}

# Recruiters emailing from personal accounts: the display name is a person, not a company
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com",
    "hotmail.com", "icloud.com", "me.com", "aol.com",
}
# ATS platforms that put the recruiter's personal name in the sender name
PERSON_DISPLAY_NAME_DOMAINS = {"paylocity.com"}

# ATS platforms where the sender name is often a parent company's account; trust the subject first
SUBJECT_FIRST_DOMAINS = {"icims.com", "icims.eu"}

# ATS platforms that send from <company>@domain, so the part before @ is the employer
LOCAL_PART_DOMAINS = {"myworkday.com"}

GENERIC_LOCAL_PARTS = {
    "no-reply", "noreply", "donotreply", "do-not-reply", "notifications",
    "notification", "jobs", "careers", "recruiting", "talent", "hr",
    "reply-to-sender", "autoreply", "mail",
}

# Body text is noisier than subjects, so only use unambiguous rejection phrases there
BODY_REJECTION_KEYWORDS = [
    "not moving forward", "other candidates", "decided not to proceed",
    "will not be moving forward", "pursue other candidates",
    "not be moving your application forward",
]


def sender_domain(sender: str) -> str:
    if "@" not in sender:
        return ""
    return sender.split("@")[-1].split(">")[0].strip().lower()

def domain_in(sender: str, domains: set[str]) -> bool:
    d = sender_domain(sender)
    return any(d == x or d.endswith("." + x) for x in domains)

def company_from_local_part(sender: str) -> str | None:
    """"quickbase@myworkday.com" -> "Quickbase"; skips generic ones like no-reply@."""
    if "@" not in sender:
        return None
    local = sender.split("@")[0].split("<")[-1].strip().lower()
    local = local.split("+")[0]
    local = re.sub(r"[_.-]?(workday[_.-]?)?notifications?$", "", local)
    if not local or local in GENERIC_LOCAL_PARTS or not re.fullmatch(r"[a-z][a-z0-9]{1,29}", local):
        return None
    return local.capitalize()

def clean_company(name: str) -> str:
    """Strips trailing greetings like "Gusto, Annabelle" -> "Gusto"."""
    name = name.strip(" ,.-|!")
    for n in sorted(KNOWN_NON_COMPANY_NAMES, key=len, reverse=True):
        name = re.sub(rf"[,\s]+{re.escape(n)}$", "", name, flags=re.IGNORECASE)
    return name.strip(" ,.-|!")

def normalize_company(name: str) -> str:
    """
    Comparison key for duplicate checks only (never written to the sheet).
    "Gusto, Inc." / "Gusto" -> "gusto", "Culture Amp" / "Cultureamp" -> "cultureamp",
    "Datadoghq" / "Datadog" -> "datadog".
    """
    n = name.strip().lower()
    # Only strip legal suffixes at the end, so "Co-Star" isn't reduced to "star"
    n = re.sub(r"[\s,.]+(inc|llc|l\.l\.c|ltd|corp|corporation)\.?$", "", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    n = re.sub(r"hq$", "", n)
    return n or name.strip().lower()

ATS_PLATFORM_NAMES = {
    "icims", "greenhouse", "lever", "workday", "ashby", "ashbyhq",
    "smartrecruiters", "gomotive", "paylocity"
}

# ATS platforms and other domains that send automated, high-volume application emails
AUTOMATED_DOMAIN_PATTERNS = [
    "greenhouse.io", "greenhouse-mail.io", "myworkday.com", "lever.co",
    "smartrecruiters.com", "icims.com", "ashbyhq.com", "gomotive.com", "icims.eu",
    "paylocity.com"
]

REJECTION_KEYWORDS = [
    "unfortunately", "not moving forward", "other candidates",
    "not selected", "decided not to proceed", "will not be moving forward",
    "pursue other candidates", "not be moving your application forward",
]

INTERVIEW_KEYWORDS = [
    "schedule", "interview", "next steps", "call with", "availability",
    "phone screen", "chat with", "speak with you",
]

OFFER_KEYWORDS = [
    "pleased to offer", "excited to extend", "offer letter", "job offer",
    "welcome to the team", "extend an offer",
]


def is_noreply_sender(sender: str) -> bool:
    return bool(re.search(r"no.?reply|donotreply", sender, re.IGNORECASE))


def is_automated_domain(sender: str) -> bool:
    sender_lower = sender.lower()
    return any(domain in sender_lower for domain in AUTOMATED_DOMAIN_PATTERNS)


def is_named_person(sender: str) -> bool:
    return "@" in sender and not is_noreply_sender(sender) and not is_automated_domain(sender)


def classify_email(sender: str, subject: str, body: str = "") -> str | None:
    """
    Returns one of: "offer", "phone screen", "rejected", or None (unclear/skip).
    Offers and interviews are read from the subject only (bodies are too noisy:
    confirmations often say "next steps"). Rejections check the body too, since
    many rejections have neutral subjects like "Thank you for your application".
    Rejection is checked before interview so "Update on your interview" + a
    rejection body is marked rejected.
    """
    subject_l = subject.lower()
    body_l = re.sub(r"\s+", " ", html.unescape(body)).lower()

    if any(kw in subject_l for kw in OFFER_KEYWORDS):
        return "offer"

    if any(kw in subject_l for kw in REJECTION_KEYWORDS) or any(kw in body_l for kw in BODY_REJECTION_KEYWORDS):
        return "rejected"

    if any(kw in subject_l for kw in INTERVIEW_KEYWORDS):
        if is_named_person(sender) or is_automated_domain(sender):
            return "phone screen"

    return None


def extract_company_from_display_name(sender: str) -> str | None:
    """
    Extracts a company name from the sender's display name
    (e.g. "CreatorIQ Talent Team <no-reply@ashbyhq.com>" -> "CreatorIQ").
    Also strips trailing ATS platform mentions like "Cadent, LLC @ icims" -> "Cadent, LLC".
    Rejects known non-company names (e.g. the user's own name, which can
    leak in from reply-thread emails) rather than returning them.
    More reliable than subject-line parsing since ATS platforms
    consistently put the real company name here.
    """
    if "<" not in sender:
        return None
    display = sender.split("<")[0].strip().strip('"').strip()
    if not display:
        return None

    if "@" in display:
        before_at = display.split("@")[0].strip()
        after_at = display.split("@")[-1].strip().lower()
        if after_at in ATS_PLATFORM_NAMES:
            display = before_at

    words = display.split()
    kept = [w for w in words if w.lower().strip(",.") not in DISPLAY_NAME_NOISE_WORDS]
    candidate = " ".join(kept).strip(" -|,.")
    candidate = re.sub(r"'s$", "", candidate)

    if candidate.lower() in KNOWN_NON_COMPANY_NAMES:
        return None

    if 1 < len(candidate) < 50:
        return candidate
    return None


def _company_from_subject(subject: str) -> str | None:
    for pattern in COMPANY_SUBJECT_PATTERNS:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match and 1 < len(match.group(1).strip()) < 50:
            return match.group(1).strip()
    return None


def extract_company_name(subject: str, sender: str) -> tuple[str, bool]:
    """
    Returns (company_name, is_reliable). is_reliable=False means a low-confidence
    guess that should be logged, not auto-written to the sheet.

    Priority: sender name > subject > domain, with two exceptions:
    - PERSONAL_EMAIL_DOMAINS / PERSON_DISPLAY_NAME_DOMAINS: sender name is a person, skip it
    - SUBJECT_FIRST_DOMAINS: sender name may be a parent company, check the subject first
    """
    person_display = domain_in(sender, PERSONAL_EMAIL_DOMAINS | PERSON_DISPLAY_NAME_DOMAINS)
    subject_first = domain_in(sender, SUBJECT_FIRST_DOMAINS)
    company = None

    if subject_first:
        company = _company_from_subject(subject)
    if company is None and not person_display:
        company = extract_company_from_display_name(sender)
    if company is None and not subject_first:
        company = _company_from_subject(subject)

    if company is None and domain_in(sender, LOCAL_PART_DOMAINS):
        company = company_from_local_part(sender)

    if company is None:
        # Domain fallback is meaningless for gmail.com, paylocity.com, etc.
        if person_display or "@" not in sender:
            return "Unknown", False
        domain_root = sender_domain(sender).split(".")[0]
        domain_root = re.sub(r"^(no-reply|noreply|mail|jobs|careers)[-.]?", "", domain_root, flags=re.IGNORECASE)
        company = domain_root.capitalize() if domain_root else "Unknown"
        # Low confidence if this is a shared ATS domain (Ashbyhq, Greenhouse-mail)
        is_reliable = not is_automated_domain(sender)
    else:
        is_reliable = True

    company = clean_company(company)

    # Final safety net, whichever method produced the name
    if company.strip().lower() in KNOWN_NON_COMPANY_NAMES:
        return company, False

    return company, is_reliable


if __name__ == "__main__":
    test_cases = [
        ("no-reply@gomotive.com", "Motive | Following up on your application for GTM AI Engineer"),
        ("no-reply.recruitment@team.wrike.com", "Thank you for applying to the Sales Strategy & Operations Analyst position at Wrike"),
        ("recruiter@somecompany.com", "Let's schedule a call to discuss next steps"),
        ("hr@somecompany.com", "Unfortunately, we've decided to move forward with other candidates"),
        ("ceo@somecompany.com", "We are pleased to offer you the position"),
    ]

    for sender, subject in test_cases:
        result = classify_email(sender, subject)
        print(f"Sender: {sender}")
        print(f"Subject: {subject}")
        print(f"Classification: {result}")
        print("-" * 40)

    print("\n--- Company name extraction tests ---")
    company_tests = [
        ("no-reply@gomotive.com", "Motive | Following up on your application for GTM AI Engineer"),
        ("no-reply.recruitment@team.wrike.com", "Thank you for applying to the Sales Strategy & Operations Analyst position at Wrike"),
        ("no-reply@us.greenhouse-mail.io", "Thank you for applying to Quantifind"),
        ("no-reply@ashbyhq.com", "Thank you for your application – Sales Operations Analyst 2039 at MeridianLink"),
        ("no-reply@us.greenhouse-mail.io", "Thank you for applying to Planful"),
        ("CreatorIQ Talent Team <no-reply@ashbyhq.com>", "Regarding Your Application at CreatorIQ"),
        ("CreatorIQ Talent Team <no-reply@ashbyhq.com>", "Thank you for your application to CreatorIQ"),
        ("Cadent, LLC @ icims <noreply@icims.com>", "Thank You For Your Application"),
        ("no-reply@us.greenhouse-mail.io", "Thank you for applying to Revenue Operations Specialist at Breeze"),
        ('"Applied Systems, Inc. @ icims" <noreply@icims.com>', "Thank You For Your Application"),
        ('"Patlytics, Inc. Team" <no-reply@ashbyhq.com>', "Thanks for applying"),
        ('"Notion\'s Team" <no-reply@ashbyhq.com>', "Thanks for applying"),
        ("Jane Recruiter <jane.recruiter@gmail.com>", "Quick chat about your application at Acme"),
        ("Jane Recruiter <jane.recruiter@gmail.com>", "Quick chat?"),
        ("Greenhouse <no-reply@greenhouse.io>", "Your application"),
        ("Kristin Sanderson <reply-to-sender@mail.paylocity.com>", "Thank You for Your Application with MOJO Family of Brands!"),
        ("PUBLICISGROUPE <publicisgroupe+autoreply@talent.icims.eu>", "Thank You for Applying to Epsilon"),
        ("quickbase@myworkday.com", "Thank You For Applying!"),
        ("no-reply@us.greenhouse-mail.io", "Thank you for applying to Gusto, Annabelle!"),
    ]
    for sender, subject in company_tests:
        company, is_reliable = extract_company_name(subject, sender)
        print(f"Subject: {subject}")
        print(f"Sender: {sender}")
        print(f"Extracted company: {company} (reliable: {is_reliable})")
        print("-" * 40)