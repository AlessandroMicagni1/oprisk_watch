"""Visual layer: CSS, header, and card rendering. Keeps ui.py focused on logic.

Palette is intentionally restrained (ink text, calm steel-blue accent, generous
whitespace) to suit a risk-quantification product. To rebrand, change ACCENT
and INK below (and primaryColor in .streamlit/config.toml)."""

import streamlit as st

ACCENT = "#2f5d8a"      # steel blue — set to Cardinal's brand hex when known
ACCENT_SOFT = "#eaf0f6"
INK = "#1a2233"
MUTED = "#6b7686"
LINE = "#e5e9f0"

# Region → small flag/label used on cards.
REGION_LABEL = {"EU": "🇪🇺 EU", "SE": "🇸🇪 SE", "NO": "🇳🇴 NO",
                "DK": "🇩🇰 DK", "FI": "🇫🇮 FI"}

# Document type → accent tint for the badge.
TYPE_TINT = {
    "Regulation": "#1b7f5c", "Directive": "#8a5a2f", "Decision": "#6a4c93",
    "Commission proposal": "#b0742f", "Recommendation": "#3d7ea6",
    "Legislation": "#2f5d8a", "News / publication": "#6b7686",
}

CSS = f"""
<style>
  /* tighten Streamlit's default top padding */
  .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1100px; }}

  /* --- header --- */
  .ow-header {{ border-bottom: 2px solid {ACCENT}; padding-bottom: .6rem; margin-bottom: .4rem; }}
  .ow-title {{ font-size: 1.9rem; font-weight: 750; color: {INK}; letter-spacing: -.02em; margin: 0; }}
  .ow-title span {{ color: {ACCENT}; }}
  .ow-sub {{ color: {MUTED}; font-size: .95rem; margin-top: .15rem; }}

  /* --- metric cards --- */
  div[data-testid="stMetric"] {{
    background: {ACCENT_SOFT}; border: 1px solid {LINE}; border-radius: 12px;
    padding: .7rem 1rem; }}
  div[data-testid="stMetricValue"] {{ color: {INK}; font-weight: 700; }}
  div[data-testid="stMetricLabel"] {{ color: {MUTED}; }}

  /* --- item cards --- */
  .ow-card {{
    border: 1px solid {LINE}; border-left: 3px solid {ACCENT};
    border-radius: 12px; padding: 1rem 1.15rem; margin-bottom: .8rem;
    background: #fff; transition: box-shadow .15s ease, transform .15s ease; }}
  .ow-card:hover {{ box-shadow: 0 4px 18px rgba(20,30,55,.08); }}
  .ow-card.new {{ border-left-color: #c0392b; }}
  .ow-ttl {{ font-size: 1.06rem; font-weight: 650; color: {INK}; line-height: 1.35; }}
  .ow-meta {{ color: {MUTED}; font-size: .82rem; margin: .15rem 0 .5rem; }}
  .ow-summary {{ color: #33405a; font-size: .93rem; line-height: 1.5; }}
  .ow-badge {{ display: inline-block; font-size: .72rem; font-weight: 700;
    padding: .12rem .5rem; border-radius: 999px; color: #fff; margin-right: .35rem; }}
  .ow-chip {{ display: inline-block; font-size: .72rem; color: {ACCENT};
    background: {ACCENT_SOFT}; border: 1px solid {LINE};
    padding: .1rem .45rem; border-radius: 999px; margin-right: .3rem; }}
  .ow-link a {{ color: {ACCENT}; font-weight: 600; text-decoration: none; font-size: .88rem; }}
  .ow-link a:hover {{ text-decoration: underline; }}
  .ow-new-tag {{ background:#c0392b; color:#fff; font-size:.68rem; font-weight:700;
    padding:.08rem .4rem; border-radius:4px; margin-right:.4rem; vertical-align:middle; }}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def header(total, last_run):
    sub = f"{total:,} items tracked"
    if last_run:
        sub += f" · last fetch {last_run} UTC"
    st.markdown(
        f"<div class='ow-header'><div class='ow-title'>OpRisk&nbsp;<span>Watch</span></div>"
        f"<div class='ow-sub'>EU &amp; Nordic operational-risk regulation — {sub}</div></div>",
        unsafe_allow_html=True,
    )


def render_card(it):
    region = REGION_LABEL.get(it["region"], it["region"])
    dtype = it.get("_type", "")
    tint = TYPE_TINT.get(dtype, MUTED)
    is_new = it.get("_is_new")
    date_str = it["published"] or "undated"

    badge = f"<span class='ow-badge' style='background:{tint}'>{dtype}</span>" if dtype else ""
    newtag = "<span class='ow-new-tag'>NEW</span>" if is_new else ""
    chips = "".join(f"<span class='ow-chip'>{t}</span>" for t in it.get("_terms", [])[:5])
    celex = f"<span class='ow-chip'>CELEX {it['celex']}</span>" if it["celex"] else ""
    summary = "" if it["prefiltered"] else f"<div class='ow-summary'>{it['summary']}</div>"
    link = (f"<div class='ow-link' style='margin-top:.5rem'>"
            f"<a href='{it['url']}' target='_blank'>↗ Open primary source</a></div>"
            if it["url"] else "")

    st.markdown(
        f"<div class='ow-card {'new' if is_new else ''}'>"
        f"{badge}{newtag}"
        f"<div class='ow-ttl'>{it['title']}</div>"
        f"<div class='ow-meta'>{region} · {date_str} · <b>{it['source']}</b></div>"
        f"{summary}"
        f"<div style='margin-top:.5rem'>{celex}{chips}</div>"
        f"{link}"
        f"</div>",
        unsafe_allow_html=True,
    )
