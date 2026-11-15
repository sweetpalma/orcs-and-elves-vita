#ifndef OE2_BAR_H
#define OE2_BAR_H

#include <stddef.h>
#include <stdint.h>

/* BREW resource archive (.bar). Data resources (type 6) carry a MIME string and
 * usually a gzip stream whose header keeps the original file name. */

typedef struct BarEntry {
	int id;          /* resource id, e.g. 1000 entities.bin, 2000 m_01.bsp */
	int type;        /* BREW resource type (6 = data) */
	uint32_t offset; /* payload offset within the archive (after the MIME header) */
	uint32_t size;   /* payload size (possibly compressed) */
	char name[64];   /* original file name from the gzip header, or "" */
} BarEntry;

typedef struct Bar {
	uint8_t *data;
	size_t size;
	BarEntry *entries;
	int count;
} Bar;

/* Supported releases (Orcs & Elves I and II, see README). */
#define BAR_EXPECTED_SIZE_OE1  2099797u
#define BAR_EXPECTED_CRC32_OE1 0x063544a5u

#define BAR_EXPECTED_SIZE_OE2  2130702u
#define BAR_EXPECTED_CRC32_OE2 0xad370c54u

#if defined(GAME_OE1)
#define BAR_EXPECTED_SIZE      BAR_EXPECTED_SIZE_OE1
#define BAR_EXPECTED_CRC32     BAR_EXPECTED_CRC32_OE1
#else
#define BAR_EXPECTED_SIZE      BAR_EXPECTED_SIZE_OE2
#define BAR_EXPECTED_CRC32     BAR_EXPECTED_CRC32_OE2
#endif

/* Returns 0 on success. */
int Bar_open(Bar *bar, const char *path);
/* 1 if the archive is exactly the supported release (size and CRC32). */
int Bar_isSupported(const Bar *bar);
void Bar_close(Bar *bar);
const BarEntry *Bar_find(const Bar *bar, int id);
const BarEntry *Bar_findByName(const Bar *bar, const char *name);
/* String resource from the .bar (type 1). Returns length, or -1 if missing. */
int Bar_loadString(const Bar *bar, int id, char *buf, int n);
/* Decompressed copy of a resource (caller frees). NULL if missing. */
uint8_t *Bar_load(const Bar *bar, int id, size_t *outSize);
uint8_t *Bar_loadByName(const Bar *bar, const char *name, size_t *outSize);

#endif
