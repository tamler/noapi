"""Tests for deterministic artifact naming."""
from app.qc.basic import generate_artifact_filename


def test_deterministic_naming_format():
    """Naming follows: prefix_plugin_tasktype_variant_hash8_timestamp.ext"""
    result = generate_artifact_filename(
        naming_prefix="char_concept",
        plugin="example_service",
        task_type="generate_image",
        variant=3,
        sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        timestamp="20260215_143022",
        extension="png",
    )
    assert result == "char_concept_example_service_generate_image_003_abcdef12_20260215_143022.png"


def test_naming_variant_zero_padded():
    """Variant number is zero-padded to 3 digits."""
    result = generate_artifact_filename(
        naming_prefix="test",
        plugin="p",
        task_type="t",
        variant=0,
        sha256="0000000011111111",
        timestamp="20260101_000000",
        extension="jpg",
    )
    assert "_000_" in result
    assert result.startswith("test_p_t_000_")


def test_naming_hash_truncated_to_8():
    """Only the first 8 characters of the SHA-256 are used."""
    sha = "deadbeef" + "0" * 56
    result = generate_artifact_filename(
        naming_prefix="x",
        plugin="p",
        task_type="t",
        variant=1,
        sha256=sha,
        timestamp="20260101_000000",
        extension="png",
    )
    assert "_deadbeef_" in result
    # Full hash should NOT appear
    assert sha not in result


def test_naming_different_inputs_different_outputs():
    """Different sha256 values produce different filenames."""
    a = generate_artifact_filename("x", "p", "t", 0, "aaaa" * 16, "20260101_000000", "png")
    b = generate_artifact_filename("x", "p", "t", 0, "bbbb" * 16, "20260101_000000", "png")
    assert a != b
