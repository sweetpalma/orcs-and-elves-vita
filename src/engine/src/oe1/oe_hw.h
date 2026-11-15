#ifndef OE_HW_H
#define OE_HW_H

#include "oe_public.h"

void Hw_setEnabled(int on);
int Hw_enabled(void);
int Hw_inScene(void);
int Hw_fastPass(void);
int Hw_queryFreeView(int *x, int *y, int *z, int *angle);
int Hw_freeView(void);

void Hw_beginScene(void);
void Hw_endScene(void);
void Hw_fadeScene(int level);
void Hw_flush(void);

void Hw_clearSources(void);
void Hw_noteSource(int kind, int where, int number);
int Hw_sourceOf(int kind, int where);

int Hw_allocTexture(void);
void Hw_resetTextures(void);
void Hw_texture(int id, int format, int width, int height, int flags, int source,
                const void *pixels, const unsigned char *mask, const unsigned short *palette);

void Hw_setRect(int x, int y, int w, int h);
short *Hw_flatTiles(void);
void *Hw_scene(void);
void *Hw_addQuad(int tex, int blend, int alpha);
void Hw_wall(int tex, int blend, int alpha, int x1, int y1, int x2, int y2,
             int zBottom, int zTop, int s1, int s2, int tTop, int tBottom);

#endif

