/** "1:22.095" — minutes:seconds.milliseconds (3dp), the standard lap-time display. */
export function formatLapTime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${minutes}:${seconds.toFixed(3).padStart(6, "0")}`;
}
