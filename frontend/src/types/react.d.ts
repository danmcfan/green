import "react"

// Lets a component pass a dynamic value to its classes as a CSS custom property,
// e.g. style={{ "--swatch": color }} with className="bg-(--swatch)".
declare module "react" {
  interface CSSProperties {
    [key: `--${string}`]: string | number | undefined
  }
}
