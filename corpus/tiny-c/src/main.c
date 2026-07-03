#include "codec.h"

int main(void) {
    unsigned char data[1] = {1};
    Decoder decoder;
    decoder_init(&decoder);
    return decode_frame(&decoder, data, 1);
}
