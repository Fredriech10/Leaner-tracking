import importlib
import os


def mark_file(filepath, marking_script, marking_setup_id=None, learner_name=None):
    if not marking_script:
        return {
            "task_name": "Unknown Task",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": "No marking script assigned to this task. Please contact your teacher.",
        }
    try:
        module = importlib.import_module(f"marking.tasks.{marking_script}")
        if learner_name and hasattr(module, "mark_for_learner"):
            return module.mark_for_learner(filepath, learner_name)
        if marking_setup_id is not None and hasattr(module, "mark_with_setup"):
            return module.mark_with_setup(filepath, int(marking_setup_id))
        return module.mark(filepath)
    except ModuleNotFoundError:
        return {
            "task_name": marking_script,
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Marking script '{marking_script}' not found. Please contact your teacher.",
        }


def get_marking_scripts():
    tasks_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "marking", "tasks")
    scripts = []
    if os.path.exists(tasks_dir):
        for filename in sorted(os.listdir(tasks_dir)):
            if filename.endswith(".py") and filename != "__init__.py" and not filename.startswith("_"):
                scripts.append(filename[:-3])
    return scripts
