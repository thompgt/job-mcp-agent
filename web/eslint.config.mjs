// eslint-config-next ships native flat config from v16, so there is no
// FlatCompat shim here — routing it through @eslint/eslintrc makes ESLint
// throw on a circular plugin reference before it lints anything.
import next from "eslint-config-next";

const config = [
  ...next,
  {
    ignores: [".next/**", "node_modules/**", "lib/schema.d.ts", "next-env.d.ts"],
  },
];

export default config;
