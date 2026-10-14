import { config } from "./config.js"

const levels = { debug: 10, info: 20, warn: 30, error: 40 } as const
type Level = keyof typeof levels

function enabled(level: Level): boolean {
  return levels[level] >= levels[config.logLevel]
}

function stamp(): string {
  return new Date().toISOString()
}

function emit(level: Level, scope: string, args: unknown[]): void {
  if (!enabled(level)) return
  const prefix = `${stamp()} [${level.toUpperCase()}] [${scope}]`
  const sink = level === "error" ? console.error : level === "warn" ? console.warn : console.log
  sink(prefix, ...args)
}

export function createLogger(scope: string) {
  return {
    debug: (...args: unknown[]) => emit("debug", scope, args),
    info: (...args: unknown[]) => emit("info", scope, args),
    warn: (...args: unknown[]) => emit("warn", scope, args),
    error: (...args: unknown[]) => emit("error", scope, args),
  }
}

export type Logger = ReturnType<typeof createLogger>
