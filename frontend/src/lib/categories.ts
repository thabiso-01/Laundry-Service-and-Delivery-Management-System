// Service categories with an icon and a short name, for the round category
// buttons on the search page and the service rows on a laundry page.

import type { IconName } from "../components/icons";

export const CATEGORY_INFO: Record<string, { name: string; icon: IconName }> = {
  wash_and_fold: { name: "Washing", icon: "washer" },
  wash_and_iron: { name: "Wash & iron", icon: "shirt" },
  ironing: { name: "Ironing", icon: "iron" },
  dry_cleaning: { name: "Dry clean", icon: "hanger" },
  bedding: { name: "Bedding", icon: "bed" },
  shoes: { name: "Shoes", icon: "shoe" },
  speciality: { name: "Speciality", icon: "sparkles" },
  other: { name: "Other", icon: "tag" },
};

// Categories shown as round buttons on the search page
export const FEATURED_CATEGORIES = ["wash_and_fold", "wash_and_iron", "ironing", "dry_cleaning", "bedding", "shoes"];
