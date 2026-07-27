import pytest
from filters.location_filter import is_brazil_eligible
from scrapers.base import RawJob


def _job(location="", description=""):
    return RawJob(source="test", url="https://x", title="Dev",
                  location=location, description=description)


@pytest.mark.parametrize("location", [
    "Worldwide", "Anywhere", "Remote", "LATAM", "Latin America",
    "Brazil", "Brasil", "Americas", "Global", "",
])
def test_open_locations_pass(location):
    assert is_brazil_eligible(_job(location=location))


@pytest.mark.parametrize("location", [
    "USA Only", "USA", "United States", "US only", "Canada",
    "UK", "Europe only", "EU only", "Germany", "Poland",
])
def test_restricted_locations_are_excluded(location):
    assert not is_brazil_eligible(_job(location=location))


def test_description_restriction_is_caught():
    # "Remote" alone says nothing about eligibility, so the description
    # restriction applies.
    job = _job(location="Remote",
               description="Great role. Candidates must be located in the US.")
    assert not is_brazil_eligible(job)

def test_description_restriction_without_allow_signal():
    job = _job(location="",
               description="Note: US citizens only, no exceptions.")
    assert not is_brazil_eligible(job)


def test_allow_location_overrides_description_boilerplate():
    job = _job(location="LATAM",
               description="Our benefits package is for US only employees "
                           "at other subsidiaries.")
    assert is_brazil_eligible(job)


# ── Local region (sudoeste do PR) ────────────────────────────────────────
from filters.location_filter import is_local_region


@pytest.mark.parametrize("location", [
    "Dois Vizinhos, PR", "Dois Vizinhos - Paraná",
    "Francisco Beltrão", "Francisco Beltrao",
    "Pato Branco/PR (híbrido)", "São João, PR", "Sao Joao - PR",
    "Ampere - PR",
])
def test_region_cities_match(location):
    assert is_local_region(location)


@pytest.mark.parametrize("location", [
    "São Paulo, SP", "Curitiba, PR", "Cascavel, PR",
    "Remoto", "Remote", "",
])
def test_outside_region_does_not_match(location):
    assert not is_local_region(location)
