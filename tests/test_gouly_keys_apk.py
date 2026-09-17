"""gouly-keys app version handling (no network access)."""

import pytest

from gouly_keys import apk
from gouly_keys.android import SetupError

# Redirect returned by APKPure for the latest Gouly Lighting app (1.8.2, version code 109).
REDIRECT = (
    "https://data.winudf.com/XAPK/Y29tLmdvdWx5bGVkLmxlZGxpZ2h0XzEwOV81ZWNmNjU3Zg"
    "?_p=Y29tLmdvdWx5bGVkLmxlZGxpZ2h0&filename=Gouly+Lighting_1.8.2_APKPure.xapk"
    "&full_size=132467175&package_name=com.goulyled.ledlight&source=web"
)


def test_release_from_redirect() -> None:
    release = apk._release_from_url(REDIRECT, "XAPK")
    assert release is not None
    assert release.version_code == 109
    assert release.version_name == "1.8.2"
    assert release.is_known_good
    assert str(release) == "1.8.2 (109)"


def test_release_from_unrelated_url() -> None:
    assert apk._release_from_url("https://apkpure.com/some/error/page", "XAPK") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("latest", None), ("LATEST", None), ("known-good", apk.KNOWN_GOOD_VERSION_CODE), ("1.8.2", 109), ("107", 107)],
)
def test_parse_version_arg(value: str, expected: int | None) -> None:
    assert apk.parse_version_arg(value) == expected


def test_parse_version_arg_rejects_names() -> None:
    with pytest.raises(SetupError):
        apk.parse_version_arg("1.7.0")
