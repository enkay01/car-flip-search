"""Tests for the unified agent-facing CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from car_flip_search import cli


def _write_market_file(path: Path) -> None:
    records = [
        {
            "id": "at-1",
            "identity": {"make": "Mercedes-Benz", "model_variant": "A180d", "registration_year": 2019},
            "mileage": 42_000,
            "cash_price": 13_200,
            "seller_type": "dealer",
        },
        {
            "id": "at-2",
            "identity": {"make": "Mercedes-Benz", "model_variant": "A180d", "registration_year": 2019},
            "mileage": 48_000,
            "cash_price": 12_950,
            "seller_type": "private",
        },
        {
            "id": "at-3",
            "identity": {"make": "Mercedes-Benz", "model_variant": "A180d", "registration_year": 2019},
            "mileage": 75_000,
            "cash_price": 11_800,
            "seller_type": "dealer",
        },
        {
            "id": "at-4",
            "identity": {"make": "Mercedes-Benz", "model_variant": "A180d", "registration_year": 2019},
            "mileage": 82_000,
            "cash_price": 11_200,
            "seller_type": "private",
        },
    ]
    path.write_text(json.dumps(records), encoding="utf-8")


def test_compare_vehicle_accepts_cli_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    market_file = tmp_path / "market.json"
    _write_market_file(market_file)

    exit_code = cli.main(
        [
            "compare-vehicle",
            "--make",
            "Mercedes-Benz",
            "--model",
            "A180d",
            "--year",
            "2019",
            "--mileage",
            "45000",
            "--cap-clean-price",
            "10000",
            "--market-file",
            str(market_file),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    envelope = json.loads(captured.out)
    assert envelope["status"] == "success"
    assert envelope["candidate"]["make"] == "Mercedes-Benz"
    assert envelope["valuation"]["comparable_supply"] == 2
    assert envelope["valuation"]["price_spread_pounds"] == 2_950
    assert len(envelope["market_comparables"]) == 2
    assert len(envelope["high_mileage_references"]) == 2


def test_compare_vehicle_accepts_json_stdin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    market_file = tmp_path / "market.json"
    _write_market_file(market_file)
    stdin = io.StringIO(
        json.dumps(
            {
                "make": "Mercedes-Benz",
                "model_variant": "A180d",
                "registration_year": 2019,
                "mileage": 45_000,
                "cap_clean_price": 10_000,
                "trim": "AMG Line",
            }
        )
    )

    exit_code = cli.main(
        ["compare-vehicle", "--json-input", "--market-file", str(market_file)],
        stdin=stdin,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    envelope = json.loads(captured.out)
    assert envelope["candidate"]["trim"] == "AMG Line"
    assert envelope["market_snapshot_summary"] == {"total_listings_observed": 4}


def test_compare_vehicle_emits_json_error_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["compare-vehicle", "--make", "BMW"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    envelope = json.loads(captured.out)
    assert envelope["status"] == "error"
    assert envelope["code"] == "invalid_input"
    assert "missing required parameters" in envelope["error"]


def test_tool_schema_is_valid_json_schema(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["tool-schema"])

    captured = capsys.readouterr()
    assert exit_code == 0
    schemas = json.loads(captured.out)
    assert isinstance(schemas, list)
    names = {item["function"]["name"] for item in schemas}
    assert names == {
        "compare-vehicle",
        "search-bca",
        "search-autotrader",
        "match-pair",
    }
    expected_parameters = {
        "compare-vehicle": {
            "json_input",
            "make",
            "model",
            "year",
            "mileage",
            "cap_clean_price",
            "trim",
            "fuel_type",
            "transmission",
            "market_file",
            "autotrader_capture_id",
            "data_root",
            "pretty",
        },
        "search-bca": {
            "search_name",
            "result_limit",
            "move_delay",
            "data_dir",
            "pretty",
            "headless",
            "catalogue_url",
            "profile_dir",
            "auth_timeout",
        },
        "search-autotrader": {
            "search_name",
            "result_limit",
            "move_delay",
            "data_dir",
            "pretty",
            "headless",
        },
        "match-pair": {
            "bca_capture_id",
            "autotrader_capture_id",
            "data_root",
            "pretty",
        },
    }
    for item in schemas:
        assert item["type"] == "function"
        function = item["function"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert set(parameters["properties"]) == expected_parameters[function["name"]]
        assert all(
            "description" in property_schema
            for property_schema in parameters["properties"].values()
        )


def test_stdout_and_stderr_are_reserved_for_machine_and_human_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._stderr("human progress")
    cli._write_json({"status": "success"})

    captured = capsys.readouterr()
    assert captured.out == '{"status": "success"}\n'
    assert captured.err == "human progress\n"


def test_bca_wait_starts_when_lot_card_dom_appears() -> None:
    class Locator:
        def count(self) -> int:
            return 1

    class Page:
        url = "https://www.bca.co.uk/catalogue"

        def locator(self, _selector: str) -> Locator:
            return Locator()

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("should not wait after cards are detected")

    cli._wait_for_bca_cards(Page(), "https://www.bca.co.uk/catalogue", 1)


def test_bca_wait_enforces_auth_timeout() -> None:
    class Locator:
        def count(self) -> int:
            return 0

    class Page:
        url = "https://www.bca.co.uk/login"

        def content(self) -> str:
            return "<html><body>login form</body></html>"

        def locator(self, _selector: str) -> Locator:
            return Locator()

        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

    with pytest.raises(TimeoutError, match="auth timeout"):
        cli._wait_for_bca_cards(Page(), "https://www.bca.co.uk/catalogue", 0.001)


def test_bca_wait_halts_immediately_on_bot_challenge() -> None:
    class Page:
        url = "https://www.bca.co.uk/catalogue"

        def content(self) -> str:
            return "<title>Access Denied - CAPTCHA</title>"

        def locator(self, _selector: str) -> object:
            raise AssertionError("challenge should be detected before card lookup")

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("challenge should not wait for auth timeout")

    with pytest.raises(cli.CaptureChallengeError, match="CAPTCHA"):
        cli._wait_for_bca_cards(Page(), "https://www.bca.co.uk/catalogue", 30)


def test_bca_wait_returns_to_deep_catalogue_after_login() -> None:
    class Locator:
        def __init__(self, page: Page) -> None:
            self._page = page

        def count(self) -> int:
            return int(self._page.url.endswith("/catalogue"))

    class Page:
        url = "https://www.bca.co.uk/login"

        def __init__(self) -> None:
            self.goto_calls: list[str] = []
            self.waits = 0

        def content(self) -> str:
            return "<html><body>login form</body></html>"

        def locator(self, _selector: str) -> Locator:
            return Locator(self)

        def goto(self, url: str, *, wait_until: str) -> None:
            assert wait_until == "domcontentloaded"
            self.goto_calls.append(url)
            self.url = url

        def wait_for_timeout(self, _milliseconds: int) -> None:
            self.waits += 1
            if self.waits == 1:
                self.url = "https://www.bca.co.uk/dashboard"

    page = Page()
    cli._wait_for_bca_cards(page, "https://www.bca.co.uk/catalogue", 1)
    assert page.goto_calls == ["https://www.bca.co.uk/catalogue"]


def test_bca_profile_defaults_to_ephemeral_session() -> None:
    args = cli._build_parser().parse_args(["search-bca", "--search-name", "daily"])
    assert args.profile_dir is None


def _write_pair_captures(data_root: Path) -> None:
    bca_dir = data_root / "bca" / "bca-1"
    autotrader_dir = data_root / "autotrader" / "at-1"
    bca_dir.mkdir(parents=True)
    autotrader_dir.mkdir(parents=True)
    (bca_dir / "records.json").write_text(
        json.dumps(
            [
                {
                    "id": "lot-1",
                    "identity": {
                        "make": "BMW",
                        "model_variant": "320d",
                        "registration_year": 2016,
                    },
                    "mileage": 117_000,
                    "cap_clean_price": 7_000,
                    "clean_condition": True,
                    "write_off_reported": False,
                    "accident_damage_reported": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    (autotrader_dir / "records.json").write_text(
        json.dumps(
            [
                {
                    "id": "listing-1",
                    "identity": {
                        "make": "BMW",
                        "model_variant": "320d",
                        "registration_year": 2016,
                    },
                    "mileage": 117_004,
                    "cash_price": 8_995,
                    "seller_type": "dealer",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_match_pair_loads_saved_captures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pair_captures(tmp_path)

    exit_code = cli.main(
        [
            "match-pair",
            "--bca-capture-id",
            "bca-1",
            "--autotrader-capture-id",
            "at-1",
            "--data-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    envelope = json.loads(captured.out)
    assert envelope["status"] == "success"
    assert len(envelope["opportunity_list"]["candidates"]) == 1
    assert envelope["opportunity_list"]["candidates"][0]["valuation"]["price_spread_pounds"] == 1_995


def test_match_pair_rejects_capture_path_traversal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(
        [
            "match-pair",
            "--bca-capture-id",
            "../outside",
            "--autotrader-capture-id",
            "at-1",
            "--data-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    envelope = json.loads(captured.out)
    assert envelope["status"] == "error"
    assert envelope["code"] == "capture_error"


def test_browser_capture_supports_headless_flag() -> None:
    parser = cli._build_parser()
    bca_default = parser.parse_args(["search-bca", "--search-name", "test"])
    assert bca_default.headless is False

    bca_headless = parser.parse_args(["search-bca", "--search-name", "test", "--headless"])
    assert bca_headless.headless is True

    at_default = parser.parse_args(["search-autotrader", "--search-name", "test"])
    assert at_default.headless is False

    at_headless = parser.parse_args(["search-autotrader", "--search-name", "test", "--headless"])
    assert at_headless.headless is True
