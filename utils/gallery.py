"""
Persistent upload galleries for Streamlit.

Streamlit's st.file_uploader keeps whatever files are currently selected
across every rerun of the script — including reruns triggered by totally
unrelated widgets elsewhere on the page. Code that reprocesses every file
in `uploaded` on each rerun (re-reading bytes, re-calling the AI) ends up
re-processing the same files dozens of times per session, and a "X uploaded"
badge derived straight from the widget's current selection goes stale the
moment the widget's own remove button is used (it doesn't fire a distinct
event we can hook).

The pattern here decouples the two: the file_uploader is treated as a
pure "add files" control and is reset (via a bumped widget key) right after
new files are absorbed into a persistent, app-owned list; that list is
rendered as its own small gallery below the uploader with per-file
View/Delete actions, independent of whatever the uploader widget is
currently showing.
"""

import base64
import html

import streamlit as st

_ICONS = {
    "application/pdf": "📄",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "📝",
    "image/jpeg": "🖼️",
    "image/png": "🖼️",
}

_MAX_INLINE_PDF_BYTES = 15 * 1024 * 1024


def _icon(mime: str) -> str:
    return _ICONS.get(mime, "📎")


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def sig(filename: str, data: bytes) -> tuple:
    """Stable identity for an uploaded file, used to dedupe against files already stored."""
    return (filename, len(data))


def uploader_key(uid: str) -> str:
    """
    Versioned widget key for `uid`. Bump with bump_uploader() after new
    files are absorbed into persistent storage so the widget resets to
    empty instead of re-offering (and causing reprocessing of) the same
    files on the next rerun.
    """
    gens = st.session_state.setdefault("_uploader_gens", {})
    return f"{uid}_{gens.get(uid, 0)}"


def bump_uploader(uid: str):
    gens = st.session_state.setdefault("_uploader_gens", {})
    gens[uid] = gens.get(uid, 0) + 1


@st.dialog("Preview", width="large")
def _preview_file(fname: str, mime: str, fb: bytes, note: str = ""):
    st.markdown(f"**{html.escape(fname)}**")
    st.caption(_fmt_size(len(fb)) + (f" · {html.escape(note)}" if note else ""))
    if mime.startswith("image/"):
        st.image(fb, width="stretch")
    elif mime == "application/pdf" and len(fb) < _MAX_INLINE_PDF_BYTES:
        b64 = base64.b64encode(fb).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="600" style="border:1px solid #e1e8f2;border-radius:8px;">'
            f"</iframe>",
            unsafe_allow_html=True,
        )
    else:
        st.info("Preview isn't available for this file type — download it to view.")
    st.download_button(
        "⬇️  Download", data=fb, file_name=fname, mime=mime, width="stretch",
    )


def _safe_image(fb: bytes, **kwargs):
    """
    st.image() raises if the bytes aren't a decodable image. A single
    corrupt/truncated upload shouldn't take down the whole page on every
    rerun for the rest of the session — show a placeholder instead.
    """
    try:
        st.image(fb, **kwargs)
    except Exception:
        st.info("⚠️ Couldn't render a preview for this photo — the file may be corrupted.")


@st.dialog("Photo", width="large")
def _preview_photo(fname: str, caption: str, fb: bytes):
    _safe_image(fb, width="stretch")
    if caption:
        st.caption(caption)
    st.download_button(
        "⬇️  Download", data=fb, file_name=fname or "photo.jpg", mime="image/jpeg",
        width="stretch",
    )


def new_uploads(existing_sigs: set, uploaded_files, process_fn) -> list:
    """
    Filters a file_uploader's current selection down to files not already
    present (by (name, size) signature) in `existing_sigs`, and runs
    `process_fn(f, fb) -> item` — any per-file work such as AI
    captioning/extraction — only on those genuinely new files.

    `existing_sigs` is mutated in place to include the new files'
    signatures. Returns the list of newly-built items; the caller appends
    them to its own persisted list and, if the list is non-empty, bumps
    the uploader's key (bump_uploader) and calls st.rerun() so the widget
    resets to empty instead of re-offering the same files next rerun.
    """
    if not uploaded_files:
        return []
    items = []
    for f in uploaded_files:
        fb = f.read()
        s = sig(f.name, fb)
        if s in existing_sigs:
            continue
        items.append(process_fn(f, fb))
        existing_sigs.add(s)
    return items


def render_file_gallery(items, on_delete, key_prefix, columns=3, extraction_note=None):
    """
    items: list of (bytes, filename, mime) tuples.
    on_delete(idx): mutate the caller's persisted list to drop index `idx`.
    extraction_note(idx, fname) -> str | None: optional one-line note
        (e.g. AI-extracted fields) shown in the preview dialog.
    """
    if not items:
        return
    cols = st.columns(columns)
    for i, (fb, fname, mime) in enumerate(items):
        with cols[i % columns]:
            with st.container(border=True):
                st.markdown(
                    f"<div style='font-size:1.35rem;line-height:1.1;'>{_icon(mime)}</div>"
                    f"<div style='font-size:0.79rem;font-weight:600;color:#1e293b;"
                    f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' "
                    f"title='{html.escape(fname)}'>{html.escape(fname)}</div>"
                    f"<div style='font-size:0.7rem;color:#94a3b8;margin-bottom:0.4rem;'>"
                    f"{_fmt_size(len(fb))}</div>",
                    unsafe_allow_html=True,
                )
                bc1, bc2 = st.columns(2)
                if bc1.button("👁 View", key=f"{key_prefix}_view_{i}", width="stretch"):
                    note = extraction_note(i, fname) if extraction_note else ""
                    _preview_file(fname, mime, fb, note or "")
                if bc2.button("🗑 Delete", key=f"{key_prefix}_del_{i}", width="stretch"):
                    on_delete(i)
                    st.rerun()


def render_photo_gallery(items, on_delete, key_prefix, columns=4):
    """items: list of (bytes, caption, mime, filename) tuples."""
    if not items:
        return
    cols = st.columns(columns)
    for i, (fb, caption, mime, fname) in enumerate(items):
        with cols[i % columns]:
            with st.container(border=True):
                _safe_image(fb, width="stretch")
                short_cap = caption if len(caption) <= 70 else caption[:67] + "…"
                st.markdown(
                    f"<div style='font-size:0.71rem;color:#475569;margin:0.3rem 0 0.4rem;"
                    f"line-height:1.3;min-height:2.6em;'>{html.escape(short_cap)}</div>",
                    unsafe_allow_html=True,
                )
                bc1, bc2 = st.columns(2)
                if bc1.button("👁", key=f"{key_prefix}_view_{i}", width="stretch", help="View full photo"):
                    _preview_photo(fname, caption, fb)
                if bc2.button("🗑", key=f"{key_prefix}_del_{i}", width="stretch", help="Delete this photo"):
                    on_delete(i)
                    st.rerun()
