"""Classification: rule engine, official-vs-third-party logic, europe helpers."""
from app.classify import classify_text, is_official_url, is_postdoc
from app.europe import detect_country, is_europe, to_code


def test_supervisor_required():
    label, conf, ev = classify_text(
        "Applicants must first contact a potential supervisor and obtain a letter "
        "of acceptance from a supervisor before submitting the application.")
    assert label == "supervisor_required"
    assert conf >= 0.5
    assert "supervisor" in ev.lower()


def test_supervisor_recommended():
    label, _, _ = classify_text(
        "Candidates are encouraged to contact a potential supervisor to discuss "
        "their research idea before applying via the portal.")
    assert label == "supervisor_recommended"


def test_direct_application():
    label, _, _ = classify_text(
        "Submit your application via the online admissions portal by 30 April. "
        "Supervisors are assigned after admission.")
    assert label == "direct_application"


def test_named_pi_postdoc():
    label, _, _ = classify_text(
        "A postdoctoral position is available in the group of Prof. Anna Weber "
        "at the Institute of Chemistry.", postdoc=True)
    assert label == "named_pi_postdoc"


def test_open_call_postdoc():
    label, _, _ = classify_text(
        "This fellowship programme invites postdoc candidates to propose your own "
        "research project in any research area.", postdoc=True)
    assert label == "open_call_postdoc"


def test_postdoc_never_gets_phd_labels():
    label, _, _ = classify_text(
        "Apply online via the application portal.", postdoc=True)
    assert label in ("named_pi_postdoc", "open_call_postdoc")


def test_default_is_low_confidence():
    label, conf, _ = classify_text("We are hiring.")
    assert label == "direct_application"
    assert conf < 0.4


def test_is_postdoc():
    assert is_postdoc({"title": "Postdoctoral Researcher in ML", "description": ""})
    assert not is_postdoc({"title": "PhD position in Economics", "description": ""})


def test_official_url_detection():
    assert is_official_url("https://www.uni-corvinus.hu/doctoral-school")
    assert is_official_url("https://www.ceu.edu/phd")
    assert is_official_url("https://www.lse.ac.uk/study")
    assert not is_official_url("https://www.findaphd.com/phds/project/x/?p123")
    assert not is_official_url("https://euraxess.ec.europa.eu/jobs/123")


def test_europe_helpers():
    assert to_code("Hungary") == "HU"
    assert to_code("uk") == "GB"
    assert is_europe("Germany") and is_europe("DE")
    assert not is_europe("Australia")
    assert is_europe("")  # unknown kept, flagged later
    assert detect_country("PhD position at the University of Debrecen, Hungary") == "HU"
