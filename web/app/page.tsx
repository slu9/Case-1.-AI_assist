import { Suspense } from "react";
import { Workspace } from "@/components/Chat";

export default function Home() {
  return (
    <Suspense fallback={null}>
      <Workspace />
    </Suspense>
  );
}
