import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|\s+|[^\s]', re.M)


def without_comments(source):
    return ''.join('\n' * part.count('\n') if part.startswith(('//', '/*')) else part
                   for part in TOKEN.findall(source))


def style_errors(path, source):
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', without_comments(source))
    errors = []
    if path.suffix != '.sv':
        errors.append('RTL and testbenches must use .sv')
    if re.search(r'\b(?:wire|reg)\b', code):
        errors.append('Use logic instead of wire/reg')
    if 'sources_1' in path.parts:
        if path.name == 'gpu_clock.sv':
            if not re.search(r'^`timescale\s+1ns\s*/\s*1ps\s*$', code, re.M):
                errors.append('gpu_clock.sv must preserve its 1ns / 1ps simulation timescale')
        elif '`timescale' in code:
            errors.append('Only gpu_clock.sv may contain an RTL timescale directive')
    for body in re.findall(r'\btypedef\s+enum\b[^{}]*\{([^}]+)\}', code, re.S):
        if '=' in body:
            errors.append('Enum members must use automatic numbering')
    if re.search(r'\bcase\s*\(state\)', code):
        if not re.search(r'\btypedef\s+enum\s+logic\s*\[\d+:0\]\s*\{', code):
            errors.append('State machines must use typedef enum logic with an explicit width')
    return errors


def format_text(source, executable=None):
    executable = executable or os.environ.get('VERIBLE_FORMAT') or shutil.which('verible-verilog-format')
    if not executable:
        raise RuntimeError('Install verible-verilog-format or set VERIBLE_FORMAT to its executable.')
    source = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', source)
    flags = ['--failsafe_success=false', '--indentation_spaces=4', '--wrap_spaces=4', '--column_limit=120',
             '--try_wrap_long_lines=false', '--compact_indexing_and_selections=true']
    for name in ('assignment_statement', 'case_items', 'enum_assignment_statement',
                 'formal_parameters', 'module_net_variable', 'parameter_declaration', 'port_declarations'):
        flags.append(f'--{name}_alignment=flush-left')
    flags += ['--named_parameter_alignment=align', '--named_port_alignment=align']
    process = subprocess.run([executable, *flags, '-'], input=source, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(process.stderr)
    source = process.stdout
    source = re.sub(r'\b(if|case|casex|casez|for|while|repeat)\s+\(', r'\1(', source)
    source = re.sub(r'\balways_ff\s+@\s*', 'always_ff@', source)
    source = re.sub(r'\)\s+begin\b', ')begin', source)
    source = re.sub(r':\s+begin\b', ':begin', source)
    source = re.sub(r'(module\s+\w+)\s*#\s*\(', r'\1 #(', source)
    source = re.sub(r'(module\s+\w+)\s+\(', r'\1(', source)
    source = re.sub(r'\]\s+\{', ']{', source)
    source = re.sub(r'\)\s*\(\n', ')(\n', source)
    source = re.sub(r'(?m)^(\s*)(\w+) #\(\n', r'\1\2\n\1#(\n', source)
    source = re.sub(r'(?m)^(\s*)\) (\w+) \(\n', r'\1)\n\1\2(\n', source)
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r'(\s*)\.([\w]+)\s*\((.*)\)(,?)\s*$', lines[i])
        if not match:
            i += 1
            continue
        group = []
        j = i
        while j < len(lines):
            item = re.match(r'(\s*)\.([\w]+)\s*\((.*)\)(,?)\s*$', lines[j])
            if not item:
                break
            group.append(item.groups())
            j += 1
        name_width = max(len(item[1]) for item in group)
        value_width = max(len(item[2].strip()) for item in group)
        lines[i:j] = [f'{indent}.{name:<{name_width}} ({value.strip():<{value_width}}){comma}'
                      for indent, name, value, comma in group]
        i = j
    source = '\n'.join(line.rstrip() for line in lines).strip() + '\n'
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--verible')
    args = parser.parse_args()
    paths = args.paths or sorted(p for p in (ROOT / 'MGPU.srcs').rglob('*') if p.suffix in ('.v', '.sv'))
    changed = []
    errors = []
    for path in paths:
        source = path.read_text(encoding='utf-8')
        label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        errors.extend(f'{label}: {message}' for message in style_errors(path, source))
        formatted = format_text(source, args.verible)
        if formatted != source or b'\r' in path.read_bytes():
            changed.append(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
            if not args.check:
                path.write_text(formatted, encoding='utf-8', newline='\n')
    print(('Needs formatting: ' if args.check else 'Formatted: ') + str(len(changed)))
    if errors:
        print('\n'.join(errors))
        raise SystemExit(1)
    if args.check and changed:
        print('\n'.join(changed))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
