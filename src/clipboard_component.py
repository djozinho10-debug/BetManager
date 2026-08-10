from pathlib import Path
import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parents[1] / 'components' / 'clipboard_paste'
_paste_component = components.declare_component('betmanager_clipboard_v2', path=str(_COMPONENT_DIR))


def clipboard_image_paste(key=None):
    return _paste_component(key=key, default=None)
