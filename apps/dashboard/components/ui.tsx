import { Button as SdkButton } from "@ui-sdk/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ComponentProps, ReactNode } from "react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const buttonVariants = cva("button", {
  variants: {
    variant: { primary: "button-primary", secondary: "button-secondary", ghost: "button-ghost", danger: "button-danger" },
    size: { normal: "", small: "button-small", icon: "button-icon" },
  },
  defaultVariants: { variant: "secondary", size: "normal" },
});

export function Button({
  className, variant, size, ...props
}: Omit<ComponentProps<typeof SdkButton>, "className"> & VariantProps<typeof buttonVariants> & { className?: string }) {
  return <SdkButton className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function Badge({
  tone = "muted", dot = false, children,
}: { tone?: "muted" | "active" | "success" | "danger" | "warning" | "purple"; dot?: boolean; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{dot && <span className="badge-dot" />}{children}</span>;
}
