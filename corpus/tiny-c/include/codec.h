#ifndef TINY_CODEC_H
#define TINY_CODEC_H

#define CODEC_OK 0

typedef struct Decoder {
    int state;
} Decoder;

void decoder_init(Decoder *decoder);
int decode_mpeg4_packet(Decoder *decoder, const unsigned char *data, int size);
int decode_frame(Decoder *decoder, const unsigned char *data, int size);

#endif
