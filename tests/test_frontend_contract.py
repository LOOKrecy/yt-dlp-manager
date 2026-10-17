from pathlib import Path


SCRIPT = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
HTML = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_tooltips_have_pointer_keyboard_and_safe_text_contract():
    assert "button.dataset.help" in SCRIPT and "tip.textContent" in SCRIPT
    assert "pointerenter" in SCRIPT and "pointerleave" in SCRIPT
    assert "aria-describedby" in SCRIPT and "event.key==='Escape'" in SCRIPT
    assert "event.preventDefault();event.stopPropagation()" in SCRIPT
    assert 'id="tooltip"' in HTML


def test_format_loading_is_finalized_and_stale_results_are_ignored():
    assert "requestId=++state.formatRequestId" in SCRIPT
    assert "requestId!==state.formatRequestId" in SCRIPT
    assert "finally" in SCRIPT and "formatsLoading').classList.add('hidden')" in SCRIPT
    assert "state.formatsCache.set(key,d)" in SCRIPT


def test_muxed_selection_clears_separate_audio_and_commands_are_distinct():
    assert "if(item.kind==='muxed')state.tempAudio=''" in SCRIPT
    assert "Команда выбранной попытки загрузки" in HTML
    assert "Команда получения форматов" in HTML
