"use client";

import { createLocalStorage, createPreference } from "@ui-sdk/core";
import { Preferences, usePreference } from "@ui-sdk/react/preferences";
import { Toggle, ToggleIcon } from "@ui-sdk/react/toggle";
import { Sun } from "lucide-react";
import type { ReactNode } from "react";
import { buttonVariants, cn } from "./ui";

const theme = createPreference({
  values: ["dark", "light"],
  defaultValue: "dark",
  attribute: "data-theme",
  global: true,
  storage: createLocalStorage("self-healing-theme"),
});

export function AppTheme({ children }: { children: ReactNode }) {
  return <Preferences preferences={[theme]}>{children}</Preferences>;
}

export function ThemeToggle() {
  const light = usePreference(theme).value === "light";
  return (
    <Toggle
      className={cn(buttonVariants({ size: "small" }), "theme-toggle")}
      pressed={light}
      onPressedChange={(pressed) => theme.set(pressed ? "light" : "dark")}
    >
      <ToggleIcon><Sun size={15} /></ToggleIcon>
      Light theme
    </Toggle>
  );
}
