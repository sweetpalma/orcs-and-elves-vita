#include "game.h"

int FreeMove_mode(void)
{
	return 0;
}

int FreeMove_stepCostsTurn(void)
{
	return 1;
}

int FreeMove_update(Canvas *cv, int canMove)
{
	(void)cv;
	(void)canMove;
	return 0;
}
