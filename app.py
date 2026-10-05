"""Gradio interface: upload -> start -> inspect -> download. Everything fits on one screen."""
import argparse
import html
import os

import gradio as gr

from pipeline.audio import ALLOWED
from pipeline.config import ROOT, list_profiles, load_config
from pipeline.errors import PipelineError
from pipeline.health import check_environment
from pipeline.orchestrator import run_pipeline_iter
from pipeline.settings import Settings

OUT_ROOT = ROOT / "outputs"
FILE_TYPES = sorted(ALLOWED)
CHANGE_HEADERS = ["Time", "From", "To"]
# (button label, file name produced by the pipeline) - order must match the `buttons` list in build()
DOWNLOADS = [("Raw transcript", "raw_transcript.txt"), ("Refined transcript", "refined_transcript.txt"),
             ("Minutes", "meeting_minutes.md"), ("Key decisions", "key_decisions.md"),
             ("Proposals", "proposals.md"), ("Action items", "action_items.md"),
             ("Full record (.md)", "meeting_record.md"), ("Full record (.json)", "meeting_record.json")]


# ---------------------------------------------------------------- small HTML helpers

def _box(kind, title, items=(), collapsed=False):
    """Coloured message box. collapsed=True hides the list behind a click (keeps the sidebar short)."""
    colors = {"bad": ("#fdecea", "#b42318"), "ok": ("#ecfdf3", "#067647"), "info": ("#eff4ff", "#175cd3")}
    bg, fg = colors[kind]
    style = f"background:{bg};color:{fg};border-radius:8px;padding:8px 12px;margin:0 0 6px;font-size:14px"
    body = "".join(f"<li>{html.escape(i)}</li>" for i in items)
    lst = f'<ul style="margin:6px 0 0 18px">{body}</ul>' if body else ""
    if collapsed and body:
        return (f'<details style="{style}"><summary style="cursor:pointer"><b>{html.escape(title)}</b></summary>'
                f"{lst}</details>")
    return f'<div style="{style}"><b>{html.escape(title)}</b>{lst}</div>'


def health_banner(profile):
    """Shown at start-up and whenever the profile changes: what is missing BEFORE a run."""
    try:
        cfg = load_config(profile)
    except PipelineError as e:
        return _box("bad", "Configuration error", [str(e)])
    problems, notes = check_environment(cfg)
    if problems:
        return _box("bad", "Fix these before running:", problems)
    out = _box("ok", f"Profile '{cfg['name']}' is ready.")
    if notes:
        out += _box("info", "Privacy and setup notes", notes, collapsed=True)
    return out


def _details(state):
    meta = state.get("meta")
    if not meta:
        return "_Shown after a run: models used, time per stage, warnings._"
    secs = meta.get("stage_seconds", {})
    lines = [f"- **Speech-to-text:** `{meta['stt_model']}`",
             f"- **LLM 1 (refinement):** `{meta['llm1_model']}`",
             f"- **LLM 2 (minutes):** `{meta['llm2_model']}`",
             f"- **Audio:** {meta['audio_seconds'] / 60:.1f} min, language: {meta.get('language') or 'unknown'}",
             "- **Time per stage:** " + ", ".join(f"{k} {v}s" for k, v in secs.items())]
    if meta.get("warnings"):
        lines += ["", "**Warnings**"] + [f"- {w}" for w in meta["warnings"]]
    return "\n".join(lines)


# ---------------------------------------------------------------- pipeline -> UI

def _view(status, state):
    """Turn pipeline state into the values of all output components (order = `outputs` in build())."""
    files = state.get("files", {})
    corr = state.get("corrections", [])
    changes = {"headers": CHANGE_HEADERS, "data": [[c["timestamp"], c["from"], c["to"]] for c in corr]}
    buttons = [gr.update(value=files.get(name), interactive=bool(files.get(name))) for _, name in DOWNLOADS]
    return (status, state.get("raw", ""), state.get("refined", ""), changes,
            state.get("minutes_md", ""), state.get("decisions_md", ""), state.get("proposals_md", ""),
            state.get("tasks_md", ""), _details(state), *buttons)


def process(mode, audio_file, audio_link, profile, topic):
    """mode is 'file' or 'link': only the input on the selected tab is used."""
    link = (audio_link or "").strip()
    if mode == "link":
        if not link:
            yield _view("Paste a link to a recording first.", {})
            return
        audio_file = None
    else:
        if not audio_file:
            yield _view("Upload a recording first.", {})
            return
        link = ""
    try:
        cfg = load_config(profile)
    except PipelineError as e:
        yield _view(f"Configuration error: {e}", {})
        return
    problems, _ = check_environment(cfg)
    if problems:
        yield _view("Setup problem:\n- " + "\n- ".join(problems), {})
        return
    for stage, msg, state in run_pipeline_iter(audio_file, cfg, out_root=str(OUT_ROOT), glossary=topic or "",
                                               audio_url=link or None):
        if stage == "done":
            status = "Done. " + msg.split("Done. ", 1)[-1]
            if state["warnings"]:
                status += f"\n{len(state['warnings'])} warning(s), see the Run details tab."
        elif stage == "failed":
            status = "Failed: " + msg
            if state.get("files"):
                status += "\n(Outputs produced before the failure are still available.)"
        else:
            status = msg
        yield _view(status, state)


# ---------------------------------------------------------------- look and feel

# Force the light theme: Gradio follows the OS dark mode unless the URL says otherwise.
FORCE_LIGHT = """
() => {
  const url = new URL(window.location);
  if (url.searchParams.get('__theme') !== 'light') {
    url.searchParams.set('__theme', 'light');
    window.location.href = url.href;
  }
}
"""

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.slate,
    font=[gr.themes.GoogleFont("IBM Plex Sans"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "monospace"],
).set(
    body_background_fill="#ffffff",
    background_fill_primary="#ffffff",
    background_fill_secondary="#f6f7f9",
    block_border_width="1px",
    block_border_color="#e3e6eb",
    block_shadow="none",
    block_radius="8px",
    block_padding="8px 10px",
    layout_gap="10px",
    button_primary_background_fill="#2450a6",
    button_primary_background_fill_hover="#1c3f84",
    button_primary_text_color="#ffffff",
)

# HEADER_H + the tab bar decide how tall the result panes can be without the page scrolling.
CSS = """
.gradio-container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
footer { display: none !important; }

/* remove the gap Gradio leaves above the first block */
.gradio-container main, .gradio-container .main, .gradio-container .wrap { padding-top: 0 !important; margin-top: 0 !important; }
#header-wrap { padding: 0 !important; margin: 0 !important; border: none !important; }

#header { padding: 6px 24px 8px; border-bottom: 1px solid #e3e6eb; }
#header h1 { margin: 0; font-size: 30px; font-weight: 700; color: #1f2430; line-height: 1.2; }
#header p { margin: 2px 0 0; color: #3d4452; font-size: 14px; font-weight: 600; }

#sidebar { padding: 14px 16px; border-right: 1px solid #e3e6eb; height: calc(100vh - 70px);
           overflow-y: auto; gap: 10px; }
#workspace { padding: 6px 20px 0; position: relative; }
#record-dl { position: absolute; top: 6px; right: 20px; width: auto !important; z-index: 5;
             gap: 8px; flex-wrap: nowrap; }
#record-dl > * { flex: none !important; min-width: 0 !important; width: auto !important; }

/* compact tab bar */
button[role="tab"] { padding: 6px 12px !important; font-size: 15px; }

/* result panes fill the remaining screen height and scroll inside themselves */
.pane textarea { height: calc(100vh - 290px) !important; max-height: none !important; }
.pane-md { height: calc(100vh - 220px); overflow-y: auto; padding-right: 8px; }
#upload { height: 120px !important; min-height: 0 !important; }

/* input source switch: two equal halves, the active one raised */
#source { border: none; padding: 0; }
#source [role="tablist"] { display: flex; background: #eef0f4; border: none; border-radius: 10px;
                           padding: 4px; gap: 4px; margin-bottom: 8px; }
#source button[role="tab"] { flex: 1; justify-content: center; border: none !important; border-radius: 8px !important;
                             padding: 7px 10px !important; color: #5b6474; background: transparent; }
#source button[role="tab"][aria-selected="true"] { background: #ffffff; color: #2450a6; font-weight: 600;
                                                   box-shadow: 0 1px 3px rgba(31, 36, 48, 0.12); }
#source button[role="tab"]::after { display: none !important; }      /* hide the default underline */

@media (max-width: 900px) {
  #sidebar { height: auto; border-right: none; border-bottom: 1px solid #e3e6eb; }
  .pane textarea { height: 50vh !important; }
  .pane-md { height: auto; }
  #record-dl { position: static; margin-bottom: 6px; }
}
"""

HEADER = """
<div id="header">
  <h1>Meeting Assistant</h1>
  <p>Upload a recording to get transcripts, minutes, decisions and action items.</p>
</div>
"""


def build():
    profiles, default = list_profiles()
    with gr.Blocks(title="Meeting Assistant", theme=THEME, css=CSS, js=FORCE_LIGHT, fill_width=True) as demo:
        gr.HTML(HEADER, elem_id="header-wrap")
        with gr.Row(equal_height=False):
            # ---- left: inputs, status, whole-record downloads
            with gr.Column(scale=0, min_width=340, elem_id="sidebar"):
                banner = gr.HTML()
                source_mode = gr.State("file")               # which input tab is active: "file" or "link"
                with gr.Tabs(elem_id="source"):
                    with gr.Tab("File upload") as tab_file:
                        audio_in = gr.File(label="Meeting recording", type="filepath", file_types=FILE_TYPES,
                                           elem_id="upload")
                    with gr.Tab("Paste link") as tab_link:
                        audio_link = gr.Textbox(label="Link to the recording", lines=1,
                                                placeholder="https://www.youtube.com/watch?v=...",
                                                info="YouTube, Vimeo or a direct audio link")
                topic = gr.Textbox(label="What is the meeting about? (optional)", lines=1,
                                   placeholder="e.g. ML deployment, Kubeflow, OAuth")
                profile = gr.Dropdown(profiles, value=default, label="Model profile (api or local)")
                go = gr.Button("Process recording", variant="primary")
                status = gr.Textbox(label="Status", lines=3, max_lines=6, interactive=False)

            # ---- right: the outputs the PS asks for
            with gr.Column(scale=1, elem_id="workspace"):
                with gr.Row(elem_id="record-dl"):
                    dl_record_md = gr.DownloadButton("Full record (.md)", interactive=False, size="sm")
                    dl_record_json = gr.DownloadButton("Full record (.json)", interactive=False, size="sm")
                with gr.Tabs():
                    with gr.Tab("Transcripts"):
                        with gr.Row():
                            with gr.Column():
                                raw = gr.Textbox(label="Raw transcript", interactive=False,
                                                 elem_classes="pane", show_copy_button=True)
                                dl_raw = gr.DownloadButton("Download raw", interactive=False, size="sm")
                            with gr.Column():
                                refined = gr.Textbox(label="Refined transcript", interactive=False,
                                                     elem_classes="pane", show_copy_button=True)
                                dl_refined = gr.DownloadButton("Download refined", interactive=False, size="sm")
                        with gr.Accordion("Corrections made by the refinement step", open=False):
                            changes = gr.Dataframe(headers=CHANGE_HEADERS, datatype=["str", "str", "str"],
                                                   interactive=False, wrap=True)
                    with gr.Tab("Minutes"):
                        minutes = gr.Markdown(elem_classes="pane-md")
                        dl_minutes = gr.DownloadButton("Download minutes", interactive=False, size="sm")
                    with gr.Tab("Decisions"):
                        with gr.Column(elem_classes="pane-md"):
                            gr.Markdown("### Agreed decisions")
                            decisions = gr.Markdown()
                            gr.Markdown("### Proposed, not agreed")
                            proposals = gr.Markdown()
                        with gr.Row():
                            dl_decisions = gr.DownloadButton("Download decisions", interactive=False, size="sm")
                            dl_proposals = gr.DownloadButton("Download proposals", interactive=False, size="sm")
                    with gr.Tab("Action items"):
                        tasks = gr.Markdown(elem_classes="pane-md")
                        dl_tasks = gr.DownloadButton("Download action items", interactive=False, size="sm")
                    with gr.Tab("Run details"):
                        details = gr.Markdown(_details({}), elem_classes="pane-md")

        # order must match DOWNLOADS, and `outputs` must match _view()
        buttons = [dl_raw, dl_refined, dl_minutes, dl_decisions, dl_proposals, dl_tasks, dl_record_md, dl_record_json]
        outputs = [status, raw, refined, changes, minutes, decisions, proposals, tasks, details, *buttons]
        tab_file.select(lambda: "file", None, source_mode)
        tab_link.select(lambda: "link", None, source_mode)
        go.click(process, [source_mode, audio_in, audio_link, profile, topic], outputs)
        profile.change(health_banner, profile, banner)
        demo.load(health_banner, profile, banner)
    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", action="store_true", help="public temporary link (handy on Colab/Kaggle)")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    try:
        max_mb = load_config()["settings"]["max_upload_mb"]
    except PipelineError:
        max_mb = Settings().max_upload_mb
    kwargs = dict(share=args.share, max_file_size=f"{max_mb}mb", allowed_paths=[str(OUT_ROOT)])
    if args.port:
        kwargs["server_port"] = args.port
    if not os.getenv("GRADIO_SERVER_NAME") and (os.getenv("SPACE_ID") or os.getenv("IN_DOCKER")):
        kwargs["server_name"] = "0.0.0.0"     # reachable from outside the container / Space
    OUT_ROOT.mkdir(exist_ok=True)
    build().queue(default_concurrency_limit=2).launch(**kwargs)


if __name__ == "__main__":
    main()