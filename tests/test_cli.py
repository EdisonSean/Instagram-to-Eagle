import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.cli import main


def test_run_dry_run_invokes_gallerydl_runner_with_normalized_url():
    with patch("ins_eagle_sync.cli.run_gallery_dl", return_value=None) as run_mock:
        exit_code = main(["run", "https://www.instagram.com/quinn.xyz/", "--dry-run"])

    assert exit_code == 0
    _, url = run_mock.call_args.args
    assert url == "https://www.instagram.com/quinn.xyz/"
    assert run_mock.call_args.kwargs["dry_run"] is True


def test_parse_staging_prints_import_item_summary(capsys):
    fake_item = type(
        "FakeImportItem",
        (),
        {
            "file_path": Path("E:/stage/item.jpg"),
            "title": "Caption ｜ ABC123_01",
            "website": "https://www.instagram.com/p/ABC123/",
            "tags": ["instagram", "author:user", "shortcode:ABC123"],
            "unique_key": "instagram:user:ABC123:01",
        },
    )()

    with patch("ins_eagle_sync.cli.scan_staging_dir", return_value=[fake_item]) as scan_mock:
        exit_code = main(["parse-staging", "E:/stage"])

    assert exit_code == 0
    scan_mock.assert_called_once_with(Path("E:/stage"))
    output = json.loads(capsys.readouterr().out)
    assert output == [
        {
            "file_path": "E:\\stage\\item.jpg",
            "title": "Caption ｜ ABC123_01",
            "website": "https://www.instagram.com/p/ABC123/",
            "tags": ["instagram", "author:user", "shortcode:ABC123"],
            "unique_key": "instagram:user:ABC123:01",
        }
    ]
