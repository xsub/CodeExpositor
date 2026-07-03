# FFmpeg Example Data

This directory contains small, checked-in samples from an FFmpeg validation run.
It intentionally does not vendor FFmpeg source code or large generated artifacts.

The real FFmpeg checkout should live outside tracked source files, for example:

```bash
.external/ffmpeg
```

`examples/ffmpeg/` contains:

- `doctor.sample.txt` - text output from `expositor doctor` after FFmpeg readiness and selected build-context readiness pass.
- `build-context.sample.json` - a captured compile command for `libavcodec/mpeg4videodec.c`.
- `mpeg4-case-study.sample.json` - a condensed MPEG-4 case-study result with the top implementation candidates.

To regenerate the full local artifacts:

```bash
cd /Users/pawel/_DEV/CodeExpositor

python3 -m expositor.cli doctor . --ffmpeg-root .external/ffmpeg

(cd .external/ffmpeg && ./configure --cc=clang --disable-everything --disable-programs --disable-doc --disable-autodetect --disable-x86asm --enable-avcodec --enable-decoder=mpeg4 --enable-parser=mpeg4video)

python3 -m expositor.cli build-context .external/ffmpeg \
  --make-target libavcodec/mpeg4videodec.o \
  --write-compile-commands compile_commands.json \
  --output /private/tmp/ffmpeg-captured-build-context.json

python3 -m expositor.cli graph .external/ffmpeg \
  --outline-source auto \
  --symbol-source auto \
  --semantic \
  --semantic-limit 1 \
  --db /private/tmp/ffmpeg-semantic-expositor.sqlite \
  --output /private/tmp/ffmpeg-semantic-graph.json

python3 -m expositor.cli case-study mpeg4 .external/ffmpeg \
  --db /private/tmp/ffmpeg-semantic-expositor.sqlite \
  --format json \
  --output /private/tmp/ffmpeg-semantic-mpeg4-case-study.json

python3 -m expositor.cli report .external/ffmpeg \
  --db /private/tmp/ffmpeg-semantic-expositor.sqlite \
  --html \
  --output /private/tmp/ffmpeg-semantic-report.html
```

The checked-in samples are meant for documentation, review and quick orientation.
Use the commands above when you want fresh full-size outputs.
