#include "player.hpp"

int mix_samples(int left, int right) {
    return left + right;
}

void Player::play() {
    mix_samples(1, 2);
}
