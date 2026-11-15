#include "oe_hw.h"
#include "oe_vm.h"
#include <stddef.h>
#include <string.h>

#ifdef OE2_STANDALONE_BRIDGE
#include "standalone_bridge.h"

int Options_count(void) {
	return 1;
}

void Options_row(int i, char *label, char *value) {
	if (i == 0) {
		strcpy(label, "Lighting:");
		strcpy(value, OE2_isRemastered() ? "On" : "Off");
	}
}

int Options_select(int i) {
	if (i == 0) {
		OE2_toggleRemastered();
		return 1;
	}
	return 0;
}

int Options_softkeyBar(void) { return 0; }
#else
/* Options stubs */
int Options_count(void) { return 0; }
void Options_row(int i, char *label, char *value) { (void)i; (void)label; (void)value; }
int Options_select(int i) { (void)i; return 0; }
int Options_softkeyBar(void) { return 0; }
#endif

/* Hw rendering stubs */
void Hw_setEnabled(int on) { (void)on; }
int Hw_enabled(void) { return 0; }
int Hw_inScene(void) { return 0; }
int Hw_fastPass(void) { return 0; }
int Hw_queryFreeView(int *x, int *y, int *z, int *angle) { (void)x; (void)y; (void)z; (void)angle; return 0; }
int Hw_freeView(void) { return 0; }

void Hw_beginScene(void) {}
void Hw_endScene(void) {}
void Hw_fadeScene(int level) { (void)level; }
void Hw_flush(void) {}

void Hw_clearSources(void) {}
void Hw_noteSource(int kind, int where, int number) { (void)kind; (void)where; (void)number; }
int Hw_sourceOf(int kind, int where) { (void)kind; (void)where; return 0; }

int Hw_allocTexture(void) { return 0; }
void Hw_resetTextures(void) {}
void Hw_texture(int id, int format, int width, int height, int flags, int source,
                const void *pixels, const unsigned char *mask, const unsigned short *palette)
{
	(void)id; (void)format; (void)width; (void)height; (void)flags; (void)source;
	(void)pixels; (void)mask; (void)palette;
}

void Hw_setRect(int x, int y, int w, int h) { (void)x; (void)y; (void)w; (void)h; }
static short dummyFlatTiles[2048];
short *Hw_flatTiles(void) { return dummyFlatTiles; }
void *Hw_scene(void) { return NULL; }
void *Hw_addQuad(int tex, int blend, int alpha) { (void)tex; (void)blend; (void)alpha; return NULL; }
void Hw_wall(int tex, int blend, int alpha, int x1, int y1, int x2, int y2,
             int zBottom, int zTop, int s1, int s2, int tTop, int tBottom)
{
	(void)tex; (void)blend; (void)alpha; (void)x1; (void)y1; (void)x2; (void)y2;
	(void)zBottom; (void)zTop; (void)s1; (void)s2; (void)tTop; (void)tBottom;
}

