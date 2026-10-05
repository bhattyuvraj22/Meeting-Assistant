"""Run the pipeline without the UI:  python cli.py meeting.mp3 --profile api"""
import argparse  # read terminal arguments
import sys  # sys.stderr for error output, sys.exit for the exit code

from pipeline.config import ROOT, load_config
from pipeline.errors import PipelineError
from pipeline.health import check_environment
from pipeline.orchestrator import run_pipeline_iter


def main(argv=None):
    ap = argparse.ArgumentParser(description="Turn a meeting recording into a transcript, minutes, decisions and tasks.")
    ap.add_argument("audio", help="path to the recording (wav, mp3, m4a, ...)")
    ap.add_argument("--profile", default=None, help="profile from config.yaml (default: the one set in the file)")
    ap.add_argument("--glossary", default="", help='domain terms, comma-separated, e.g. "Kubeflow, OAuth"')
    ap.add_argument("--out", default=str(ROOT / "outputs"), help="folder for run outputs")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.profile)
    except PipelineError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1
    problems, notes = check_environment(cfg)
    for n in notes:
        print(f"note: {n}")
    if problems:
        print("Setup problems:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 1
    final = None
    for stage, msg, state in run_pipeline_iter(args.audio, cfg, out_root=args.out, glossary=args.glossary):
        print(f"[{stage}] {msg}")
        final = (stage, msg, state)
    stage, msg, state = final
    if stage == "failed":
        print(f"Failed: {msg}", file=sys.stderr)
        return 1
    for w in state["warnings"]:
        print(f"warning: {w}")
    print(f"\nOutputs are in: {state['out_dir']}")
    for name in state["files"]:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
