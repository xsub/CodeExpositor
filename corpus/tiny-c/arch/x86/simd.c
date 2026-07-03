#include "../../include/codec.h"

#if defined(__x86_64__)
int x86_idct(Decoder *decoder) {
    return decoder->state;
}
#endif
