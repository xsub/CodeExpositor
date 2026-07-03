# Tiny C Codec

Tiny C Codec is a small validation corpus for Code Expositor.

## Decoder Flow

The public frame decoder calls the MPEG-4 packet decoder through a direct C function call.

## Architecture Notes

The `arch/x86` directory contains x86-specific code guarded by architecture macros.
