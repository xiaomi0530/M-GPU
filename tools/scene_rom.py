from pathlib import Path
import re
import shutil


def write_rom(assignments, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    arrays = {}
    pattern = r"(\w+)\[(\d+)\]\s*=\s*(\d+)'([dh])([0-9a-f]+);"
    for name, index, width, base, value in re.findall(pattern, assignments):
        arrays.setdefault(name, []).append((int(index), int(width), int(value, 16 if base == 'h' else 10)))
    for name, values in arrays.items():
        lines = []
        next_index = 0
        for index, width, value in values:
            if index != next_index:
                lines.append(f'@{index:x}')
            lines.append(f'{value:0{(width + 3) // 4}x}')
            next_index = index + 1
        (directory / f'scene_{name}.mem').write_text('\n'.join(lines) + '\n', encoding='ascii')


def stage_rom(project, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = sorted((Path(project) / 'MGPU.srcs/sources_1/rom').glob('*.mem'))
    if len(files) != 8:
        raise FileNotFoundError('Expected eight scene ROM files in MGPU.srcs/sources_1/rom')
    for source in files:
        destination = output / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
