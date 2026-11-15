#ifndef OE_STANDALONE_BRIDGE_H
#define OE_STANDALONE_BRIDGE_H

#include <stdint.h>

void OE_setRemastered(int enabled);
int OE_isRemastered(void);
int OE_toggleRemastered(void);
void OE_loadHostConfig(void);
void OE_saveHostConfig(void);
int OE_isFastTick(void);
int OE_toggleFastTick(void);
int OE_getTickMs(void);
void OE_setSkipPresent(int skip);
int OE_shouldSkipPresent(void);
void OE_presentFrame(const uint16_t *fb, int pitchPixels, int scrW, int scrH, uint32_t *outRgba);

#endif

