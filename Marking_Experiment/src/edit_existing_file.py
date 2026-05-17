# src/edit_existing_file.py
import json
import sys

def apply_changes(filepath, changes):
    file_content = read_file(filepath)
    new_content = file_content.replace(changes.split(' -> ')[0], changes.split(' -> ')[1])
    write_file(filepath, new_content)

def read_file(filepath):
    with open(filepath, 'r') as file:
        return file.read()

def write_file(filepath, content):
    with open(filepath, 'w') as file:
        file.write(content)

if __name__ == "__main__":
    filepath = sys.argv[1]
    changes_str = sys.argv[2]
    changes = json.loads(changes_str)
    apply_changes(filepath, changes)