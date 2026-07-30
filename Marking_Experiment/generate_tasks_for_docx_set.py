import json
from pathlib import Path
from typing import Dict, List, Tuple


def _sanitize_filename(name: str) -> str:
    # Keep readable names but strip characters that often break filenames.
    bad = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    for ch in bad:
        name = name.replace(ch, '_')
    return name.strip()


def load_structured_expectations(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_task_from_structured(structured: Dict) -> Dict:
    # Reuse the existing conversion logic but we intentionally keep it simple here:
    # - create a "single task json" that the engine can run against any learner submission
    #
    # NOTE: This generator does NOT attempt to rewrite domains/types.
    # It simply maps the structured checks into the engine's expected question format
    # by calling the existing converter script if available.
    #
    # For safety and to avoid coupling to internal mapping, we perform the mapping inline
    # using Marking_Experiment/structured_expectations_to_task.py by importing convert()
    # behavior is tricky; so instead we do a direct conversion by invoking that script’s code.
    #
    # To keep this file minimal and safe, we just call the converter and read its output.
    raise RuntimeError("This function should not be called directly. Use convert_and_load().")


def convert_and_load(structured_path: Path) -> Dict:
    import runpy

    # Repo root = folder containing this file's parent.parent
    repo_root = Path(__file__).resolve().parent.parent

    converter = repo_root / "Marking_Experiment" / "structured_expectations_to_task.py"
    out_task = repo_root / "task_from_structured_expectations.json"

    runpy.run_path(str(converter), run_name="__main__")
    return json.loads(out_task.read_text(encoding="utf-8"))


def infer_question_paper_name(docx_file_name: str) -> str:
    # For names like:
    #  - "COMPUTER APPLICATIONS TECHNOLOGY test 1 qp.docx"
    #  - "COMPUTER APPLICATIONS TECHNOLOGY test 1 memo.docx"
    #  - "COMPUTER APPLICATIONS TECHNOLOGY test 1 (3).docx" (not expected)
    #
    # We'll strip suffixes:
    #  " qp.docx", " memo.docx", " learner data.docx", " learner_data.docx", " learner data.docx"
    n = docx_file_name
    lower = n.lower()
    for suffix in [" qp.docx", " memo.docx", " learner data.docx", " learner_data.docx"]:
        if lower.endswith(suffix):
            return _sanitize_filename(n[: -len(suffix)])
    # fallback: strip extension
    if lower.endswith(".docx"):
        return _sanitize_filename(n[: -len(".docx")])
    return _sanitize_filename(n)


def generate_per_docx_tasks(structured_expectations_path: Path) -> List[Tuple[Path, Path, str]]:
    base = structured_expectations_path.parent  # repo root

    # We'll output into repo root subfolders as requested: json QP/, json Memo/, json Learner/
    out_qp_dir = base / "json QP"
    out_memo_dir = base / "json Memo"
    out_learner_dir = base / "json Learner"
    out_qp_dir.mkdir(parents=True, exist_ok=True)
    out_memo_dir.mkdir(parents=True, exist_ok=True)
    out_learner_dir.mkdir(parents=True, exist_ok=True)

    # Find docx files in repo root (current environment shows they are directly under repo root)
    repo_root = base
    docx_files = list(repo_root.glob("*.docx"))

    # Identify categories
    qp_files = [p for p in docx_files if " qp.docx" in p.name.lower()]
    memo_files = [p for p in docx_files if " memo.docx" in p.name.lower()]
    learner_files = [
        p
        for p in docx_files
        if ("learner" in p.name.lower()) and p.name.lower().endswith(".docx") and ("data" in p.name.lower())
    ]

    # If your learner submission docs use a different naming, extend here.
    # For now, use these patterns.

    # Convert to engine-format once.
    engine_task = convert_and_load(structured_expectations_path)

    generated: List[Tuple[Path, Path, str]] = []

    # Create one task json per learner doc category (same questions for now).
    for learner_path in learner_files:
        paper = infer_question_paper_name(learner_path.name)
        learner_task_path = out_learner_dir / f"{paper}_learner.json"
        task_copy = dict(engine_task)
        task_copy["file"] = learner_path.name
        learner_task_path.write_text(json.dumps(task_copy, indent=2, ensure_ascii=False), encoding="utf-8")
        generated.append((learner_task_path, learner_path, "learner"))

    for qp_path in qp_files:
        paper = infer_question_paper_name(qp_path.name)
        qp_task_path = out_qp_dir / f"{paper}_qp.json"
        task_copy = dict(engine_task)
        task_copy["file"] = qp_path.name
        qp_task_path.write_text(json.dumps(task_copy, indent=2, ensure_ascii=False), encoding="utf-8")
        generated.append((qp_task_path, qp_path, "qp"))

    for memo_path in memo_files:
        paper = infer_question_paper_name(memo_path.name)
        memo_task_path = out_memo_dir / f"{paper}_memo.json"
        task_copy = dict(engine_task)
        task_copy["file"] = memo_path.name
        memo_task_path.write_text(json.dumps(task_copy, indent=2, ensure_ascii=False), encoding="utf-8")
        generated.append((memo_task_path, memo_path, "memo"))

    return generated


def main():
    structured_expectations_path = Path(__file__).resolve().parent.parent / "structured_expectations.json"
    print("DEBUG structured_expectations_path:", structured_expectations_path)
    print("DEBUG base repo:", structured_expectations_path.parent.parent)
    gen = generate_per_docx_tasks(structured_expectations_path)
    print(f"Generated {len(gen)} per-docx task json files.")
    for tpath, docx, kind in gen[:30]:
        print(kind, tpath.name, "->", docx.name)


if __name__ == "__main__":
    main()
