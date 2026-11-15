#ifndef OE_PUBLIC_H
#define OE_PUBLIC_H

#define OE_MOVE_TURNS 0
#define OE_MOVE_STEPS 1
#define OE_MOVE_TIMER 2

typedef struct {
	int mode;
	int forward;
	int side;
	int yaw;
	int speed;
	int turnMs;
} oeFreeMove_t;

#define OE_HWTEX_REPEAT 0x01
#define OE_HWTEX_GREY   0x02
#define OE_HWTEX_BRIGHT 0x04

#define OE_HWSRC_WALL   1
#define OE_HWSRC_SPRITE 2
#define OE_HWSRC_FLAT   3
#define OE_HWSRC(kind, n) (((kind) << 24) | (n))

#endif

