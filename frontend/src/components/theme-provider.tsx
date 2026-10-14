import { createContext, type ReactNode, use, useEffect, useState } from "react"
import { z } from "zod"

export const Theme = z.enum(["light", "dark", "system"])
export type Theme = z.infer<typeof Theme>
const STORAGE_KEY = "green-theme"
const DARK = window.matchMedia("(prefers-color-scheme: dark)")

const ThemeContext = createContext<{
  theme: Theme
  resolved: "light" | "dark"
  setTheme: (theme: Theme) => void
} | null>(null)

/** Light, dark, or the system's choice; the choice is remembered, and `.dark` goes on <html>. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() =>
    Theme.catch("system").parse(localStorage.getItem(STORAGE_KEY))
  )
  const [systemDark, setSystemDark] = useState(DARK.matches)

  useEffect(() => {
    const onChange = (event: MediaQueryListEvent) =>
      setSystemDark(event.matches)
    DARK.addEventListener("change", onChange)
    return () => DARK.removeEventListener("change", onChange)
  }, [])

  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme
  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark")
    document.documentElement.style.colorScheme = resolved
  }, [resolved])

  const setTheme = (next: Theme) => {
    localStorage.setItem(STORAGE_KEY, next)
    setThemeState(next)
  }

  return (
    <ThemeContext value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext>
  )
}

export function useTheme() {
  const context = use(ThemeContext)
  if (!context) throw new Error("useTheme needs a ThemeProvider")
  return context
}
