import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ziia — préparation d'annonces",
  description:
    "Préparation des articles, des photos et des variantes avant publication.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body>
        <div className="mx-auto max-w-6xl px-4 py-8">{children}</div>
      </body>
    </html>
  );
}
