#include "codec.h"
#include <stddef.h>

void decoder_init(Decoder *decoder) {
    if (decoder == NULL) {
        return;
    }
    decoder->state = CODEC_OK;
}

int decode_mpeg4_packet(Decoder *decoder, const unsigned char *data, int size) {
    if (decoder == NULL || data == NULL || size <= 0) {
        return -1;
    }
    decoder->state += data[0];
    return decoder->state;
}

int decode_frame(Decoder *decoder, const unsigned char *data, int size) {
    return decode_mpeg4_packet(decoder, data, size);
}
