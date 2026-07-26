"""Unit tests for IDF exporter."""

from __future__ import annotations

from pathlib import Path

from app.energyplus.idf_exporter import export_modified_idf


def test_export_modified_idf_fallback(tmp_path: Path, test_config):
    non_existent_base = tmp_path / "non_existent_base.idf"
    out_file = tmp_path / "modified_test.idf"
    res = export_modified_idf(
        "non_existent_sim", base_idf_path=non_existent_base, output_path=out_file
    )
    assert res.exists()
    assert "Eco-Loop AI-Optimized Simulation Run" in res.read_text(encoding="utf-8")


def test_export_modified_idf_with_base_file(tmp_path: Path, test_config):
    base_idf = tmp_path / "base.idf"
    base_idf.write_text(
        """  Schedule:Compact,
    CLGSETP_SCH,
    Temperature,
    Through: 12/31,
    Until: 24:00,24.0;

  Schedule:Compact,
    HTGSETP_SCH,
    Temperature,
    Through: 12/31,
    Until: 24:00,20.0;
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "modified_output.idf"
    res = export_modified_idf("non_existent_sim", base_idf_path=base_idf, output_path=out_file)

    assert res.exists()
    content = res.read_text(encoding="utf-8")
    assert "ECO-LOOP AI-OPTIMIZED BUILDING MODEL" in content
    assert "CLGSETP_SCH" in content
    assert "HTGSETP_SCH" in content
