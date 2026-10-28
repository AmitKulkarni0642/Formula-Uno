import { redirect } from "next/navigation";

export default async function EventPage({
  params,
}: {
  params: Promise<{ season: string; round: string }>;
}) {
  const { season, round } = await params;
  redirect(`/${season}/${round}/quali`);
}
