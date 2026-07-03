"""Build context loading from compile_commands.json."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True)
class CompileCommand:
    file: str
    directory: str
    arguments: list[str]
    include_paths: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    target_arch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "directory": self.directory,
            "arguments": self.arguments,
            "include_paths": self.include_paths,
            "macros": self.macros,
            "target_arch": self.target_arch,
        }


@dataclass
class BuildContext:
    compile_commands_path: str | None
    translation_units: list[CompileCommand] = field(default_factory=list)

    def by_file(self, file: str) -> list[CompileCommand]:
        return [item for item in self.translation_units if item.file == file]

    def to_dict(self) -> dict[str, Any]:
        return {
            "compile_commands_path": self.compile_commands_path,
            "translation_units": [item.to_dict() for item in self.translation_units],
        }


def _relative_or_absolute(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _arguments(item: dict[str, Any]) -> list[str]:
    if "arguments" in item and isinstance(item["arguments"], list):
        return [str(value) for value in item["arguments"]]
    command = str(item.get("command", ""))
    return shlex.split(command)


def _parse_arguments(args: list[str]) -> tuple[list[str], list[str], str | None]:
    include_paths: list[str] = []
    macros: list[str] = []
    target_arch: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-I" and index + 1 < len(args):
            include_paths.append(args[index + 1])
            index += 2
            continue
        if arg.startswith("-I") and len(arg) > 2:
            include_paths.append(arg[2:])
        elif arg == "-D" and index + 1 < len(args):
            macros.append(args[index + 1])
            index += 2
            continue
        elif arg.startswith("-D") and len(arg) > 2:
            macros.append(arg[2:])
        elif arg in {"-target", "--target"} and index + 1 < len(args):
            target_arch = args[index + 1]
            index += 2
            continue
        elif arg.startswith("--target="):
            target_arch = arg.split("=", 1)[1]
        elif arg == "-arch" and index + 1 < len(args):
            target_arch = args[index + 1]
            index += 2
            continue
        index += 1
    return sorted(set(include_paths)), sorted(set(macros)), target_arch


def load_build_context(root: str | Path) -> BuildContext:
    root_path = Path(root).resolve()
    compile_commands = root_path / "compile_commands.json"
    if not compile_commands.exists():
        return BuildContext(compile_commands_path=None)

    payload = json.loads(compile_commands.read_text(encoding="utf-8"))
    commands: list[CompileCommand] = []
    for item in payload:
        directory = Path(str(item.get("directory", root_path)))
        if not directory.is_absolute():
            directory = root_path / directory
        directory = directory.resolve()
        file_path = Path(str(item.get("file", "")))
        if not file_path.is_absolute():
            file_path = directory / file_path
        args = _arguments(item)
        includes, macros, target_arch = _parse_arguments(args)
        commands.append(
            CompileCommand(
                file=_relative_or_absolute(file_path, root_path),
                directory=_relative_or_absolute(directory, root_path),
                arguments=args,
                include_paths=includes,
                macros=macros,
                target_arch=target_arch,
            )
        )

    commands.sort(key=lambda item: (item.file, item.directory, item.arguments))
    return BuildContext(
        compile_commands_path=compile_commands.relative_to(root_path).as_posix(),
        translation_units=commands,
    )


def _compiler_command(args: list[str]) -> bool:
    if not args:
        return False
    compiler = Path(args[0]).name
    if compiler == "ccache" and len(args) > 1:
        compiler = Path(args[1]).name
    return compiler in {"cc", "gcc", "clang", "c++", "g++", "clang++"}


def _source_argument(args: list[str], root: Path) -> str | None:
    source_suffixes = {".c", ".cc", ".cpp", ".cxx", ".m", ".mm"}
    for arg in reversed(args):
        if arg.startswith("-"):
            continue
        path = Path(arg)
        if path.suffix.lower() not in source_suffixes:
            continue
        if path.is_absolute():
            try:
                return path.resolve().relative_to(root).as_posix()
            except ValueError:
                return path.resolve().as_posix()
        if (root / path).exists():
            return path.as_posix()
    return None


def capture_make_build_context(
    root: str | Path,
    targets: list[str],
    *,
    make: str = "make",
) -> BuildContext:
    root_path = Path(root).resolve()
    make_path = shutil.which(make)
    if make_path is None:
        raise RuntimeError(f"{make} not found")
    commands: dict[str, CompileCommand] = {}
    for target in targets:
        process = subprocess.run(
            [make_path, "-n", "V=1", target],
            cwd=root_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip()
            raise RuntimeError(f"make dry-run failed for {target}: {detail}")
        for line in process.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                args = shlex.split(line)
            except ValueError:
                continue
            if not _compiler_command(args):
                continue
            source_file = _source_argument(args, root_path)
            if source_file is None:
                continue
            includes, macros, target_arch = _parse_arguments(args)
            commands[source_file] = CompileCommand(
                file=source_file,
                directory=".",
                arguments=args,
                include_paths=includes,
                macros=macros,
                target_arch=target_arch,
            )
    return BuildContext(
        compile_commands_path=None,
        translation_units=sorted(commands.values(), key=lambda item: item.file),
    )


def write_compile_commands(
    root: str | Path,
    context: BuildContext,
    output: str | Path | None = None,
) -> Path:
    root_path = Path(root).resolve()
    output_path = Path(output) if output else root_path / "compile_commands.json"
    if not output_path.is_absolute():
        output_path = root_path / output_path
    payload = []
    for command in context.translation_units:
        directory = root_path / command.directory if command.directory != "." else root_path
        payload.append(
            {
                "directory": directory.resolve().as_posix(),
                "file": command.file,
                "arguments": command.arguments,
            }
        )
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path
