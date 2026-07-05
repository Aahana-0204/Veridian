/** Simple className joiner — avoids pulling in clsx/tailwind-merge. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
