#ifndef OE_VM_H
#define OE_VM_H

#include "oe_public.h"

int Options_count(void);
void Options_row(int i, char *label, char *value);
int Options_select(int i);
int Options_softkeyBar(void);

#endif

