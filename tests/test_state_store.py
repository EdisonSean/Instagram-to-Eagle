import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ins_eagle_sync.state_store import ImportedState, import_key


def test_import_key_uses_shortcode_and_media_index():
    assert import_key("ABC123", 3) == "ABC123:3"


def test_state_store_round_trip(tmp_path):
    path = tmp_path / "state" / "imported.json"
    state = ImportedState.load(path)

    assert not state.has_imported("ABC123", 1)

    state.mark_imported("ABC123", 1)
    state.save()

    loaded = ImportedState.load(path)
    assert loaded.has_imported("ABC123", 1)
    assert not loaded.has_imported("ABC123", 2)
