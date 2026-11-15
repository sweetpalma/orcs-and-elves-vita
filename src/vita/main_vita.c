/* Orcs & Elves II — PS Vita host loop.
 * Preserves the original 40 ms BREW simulation timer while providing
 * responsive gamepad auto-repeat and clean Vita process shutdown. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <SDL.h>

#include "game.h"
#include "standalone_bridge.h"

#ifdef __vita__
#include <psp2/io/stat.h>
#include <psp2/kernel/processmgr.h>
#endif

#if defined(GAME_OE1)
#define GAME_TITLE "Orcs & Elves"
#define GAME_BAR_FILE "orcsandelves.bar"
#define GAME_MOD_FILE "orcsandelves.mod"
#define GAME_PRIMARY_DIR "ux0:data/oe1"
#define GAME_FALLBACK_DIR "ux0:data/oe"
#else
#define GAME_TITLE "Orcs & Elves II"
#define GAME_BAR_FILE "orcsandelves2.bar"
#define GAME_MOD_FILE "orcsandelves2.mod"
#define GAME_PRIMARY_DIR "ux0:data/oe2"
#endif

#define TICK_MS 40
#define KEY_REPEAT_START 320
#define KEY_REPEAT_RATE 80
#define KB_AUTOREPEAT 0x40

static const char *resolve_data_dir(void) {
  static const char *const candidates[] = {
      GAME_PRIMARY_DIR,
#if defined(GAME_FALLBACK_DIR)
      GAME_FALLBACK_DIR,
#endif
      "app0:data",
      "data",
  };
#ifdef __vita__
  sceIoMkdir("ux0:data", 0777);
  sceIoMkdir(GAME_PRIMARY_DIR, 0777);
  sceIoMkdir(GAME_PRIMARY_DIR "/saves", 0777);
#endif
  for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); i++) {
    char bar_path[256];
    char mod_path[256];
    snprintf(bar_path, sizeof(bar_path), "%s/" GAME_BAR_FILE, candidates[i]);
    snprintf(mod_path, sizeof(mod_path), "%s/" GAME_MOD_FILE, candidates[i]);
    FILE *fb = fopen(bar_path, "rb");
    FILE *fm = fopen(mod_path, "rb");
    if (fb && fm) {
      fclose(fb);
      fclose(fm);
      return candidates[i];
    }
    if (fb)
      fclose(fb);
    if (fm)
      fclose(fm);
  }
  return NULL;
}

int main(int argc, char **argv) {
  const char *data = resolve_data_dir();
  int w = 352, h = 200;
  Applet *app;
  uint32_t nextTick;

  (void)argc;
  (void)argv;

  if (!data) {
#if defined(GAME_OE1)
    Plat_showError(
        GAME_TITLE,
        "Could not find game data!\n\n"
        "Please copy " GAME_BAR_FILE " and " GAME_MOD_FILE "\n"
        "to " GAME_PRIMARY_DIR "/ (or " GAME_FALLBACK_DIR "/)");
#else
    Plat_showError(
        GAME_TITLE,
        "Could not find game data!\n\n"
        "Please copy " GAME_BAR_FILE " and\n"
        GAME_MOD_FILE " to " GAME_PRIMARY_DIR "/");
#endif
    return 1;
  }

  if (Brew_init(data, w, h) != 0) {
    char msg[256];
    snprintf(msg, sizeof(msg),
             "Failed to load game data from:\n%s\n\n"
             "Please check that " GAME_BAR_FILE " and\n"
             GAME_MOD_FILE " are valid BREW 7.0.41 files.",
             data);
    Plat_showError(GAME_TITLE, msg);
    return 1;
  }
  if (Plat_init(w, h, GAME_TITLE) != 0) {
    Brew_shutdown();
#ifdef __vita__
    sceKernelExitProcess(1);
#endif
    return 1;
  }
  Audio_init();

  app = App_create(w, h);
  if (!app) {
    Plat_showError(GAME_TITLE, "Engine startup failed.\nOut of memory or corrupted data.");
    Plat_shutdown();
    Brew_shutdown();
#ifdef __vita__
    sceKernelExitProcess(1);
#endif
    return 1;
  }
  Applet_HandleEvent(app, EVT_APP_START, 0, 0);

  nextTick = Plat_uptimeMs();
  int heldKey = 0, suspended = 0;
  uint32_t nextRepeat = 0;
  for (;;) {
    PlatKeyEvent ev[32];
    int n;
    if (!Plat_pollEvents(ev, 32, &n))
      break;
    if (Plat_isMinimized() != suspended) {
      suspended = !suspended;
      heldKey = 0;
      Applet_HandleEvent(app, suspended ? EVT_APP_SUSPEND : EVT_APP_RESUME, 0,
                         0);
    }
    for (int i = 0; i < n && !suspended; i++) {
      if (ev[i].repeat)
        continue;
      if (ev[i].down) {
        Applet_HandleEvent(app, EVT_KEY, ev[i].avk, 0);
        heldKey = ev[i].avk;
        nextRepeat = Plat_uptimeMs() + KEY_REPEAT_START;
      } else {
        if (ev[i].avk == heldKey)
          heldKey = 0;
        Applet_HandleEvent(app, EVT_KEY_RELEASE, ev[i].avk, 0);
      }
    }
    if (heldKey && (int32_t)(Plat_uptimeMs() - nextRepeat) >= 0) {
      Applet_HandleEvent(app, EVT_KEY, heldKey, KB_AUTOREPEAT);
      nextRepeat += KEY_REPEAT_RATE;
      if ((int32_t)(Plat_uptimeMs() - nextRepeat) >= 0)
        nextRepeat = Plat_uptimeMs() + KEY_REPEAT_RATE;
    }
    if (Brew_quitRequested())
      break;
    uint32_t now = Plat_uptimeMs();
    if ((int32_t)(now - nextTick) >= 0) {
      uint32_t step = (uint32_t)OE2_getTickMs();
      int budget = 4;
      while ((int32_t)(now - nextTick) >= 0 && budget-- > 0) {
        nextTick += step;
        int moreDue = ((int32_t)(now - nextTick) >= 0 && budget > 0);
        OE2_setSkipPresent(moreDue);
        Applet_Tick(app);
        if (Brew_quitRequested())
          break;
      }
      OE2_setSkipPresent(0);
      uint32_t after = Plat_uptimeMs();
      if ((int32_t)(after - nextTick) > (int32_t)(step * 4u))
        nextTick = after;
    } else {
      Plat_delay(1);
    }
  }

  Applet_HandleEvent(app, EVT_APP_STOP, 0, 0);
  App_destroy(app);
  Plat_shutdown();
  Brew_shutdown();
#ifdef __vita__
  sceKernelExitProcess(0);
#endif
  return 0;
}
