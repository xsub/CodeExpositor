#include "codec.h"

int probe_external_decoder(Decoder *decoder) {
    return external_decoder_probe(decoder);
}
