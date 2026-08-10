import type { ReactNode } from "react";

import type { RuntimeMeta } from "./api";
import { defaultRuntime, RuntimeContext } from "./runtime";

export function RuntimeProvider({
  value,
  children,
}: {
  value?: RuntimeMeta;
  children: ReactNode;
}) {
  return (
    <RuntimeContext.Provider value={value ?? defaultRuntime}>
      {children}
    </RuntimeContext.Provider>
  );
}
